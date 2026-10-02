"""Authenticated, default-off private Word document API."""

import hashlib
import os
import unicodedata
from io import BytesIO
from typing import Annotated
from urllib.parse import quote
from uuid import UUID

from fastapi import APIRouter, Depends, File, Form, Header, UploadFile
from sqlalchemy.orm import Session
from starlette.responses import Response

from onyx.auth.permissions import require_permission
from onyx.configs.constants import FileOrigin
from onyx.db import word_documents as db
from onyx.db.engine.sql_engine import get_session
from onyx.db.enums import Permission
from onyx.db.models import User
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
from onyx.file_store.file_store import get_default_file_store
from onyx.word_documents.contracts import DocumentSnapshot, VersionResult, WordStatus
from onyx.word_documents.validation import (
    DOCX_MIME,
    MAX_DOCX_BYTES,
    blank_docx,
    validate_docx,
)

router = APIRouter(prefix="/orgmesh/documents", tags=["Word documents"])
require_word_user = require_permission(Permission.BASIC_ACCESS)


def _enabled() -> bool:
    return os.environ.get("ORGMESH_WORD_ENABLED", "false").lower() == "true"


def _require_enabled() -> None:
    if not _enabled():
        raise OnyxError(OnyxErrorCode.ENV_VAR_GATED, "Word documents are disabled")


def _filename(title: str) -> str:
    safe = "".join(
        char
        for char in title
        if char not in "/\\" and not unicodedata.category(char).startswith("C")
    ).strip()
    safe = safe or "Untitled document"
    if safe.lower().endswith(".docx"):
        return safe
    return safe[:250] + ".docx"


def _upload(file: UploadFile) -> bytes:
    content = file.file.read(MAX_DOCX_BYTES + 1)
    validate_docx(content)
    return content


def _store(owner: UUID) -> db.StoreVersion:
    def save(version_id: UUID, content: bytes) -> str:
        file_store = get_default_file_store()
        file_id = file_store.save_file(
            content=BytesIO(content),
            display_name="document.docx",
            file_origin=FileOrigin.ORGMESH_WORD,
            file_type=DOCX_MIME,
            file_id=f"orgmesh-word/{owner}/{version_id}.docx",
        )

        with file_store.read_file(file_id, mode="b") as stored:
            actual = stored.read(MAX_DOCX_BYTES + 1)
        if hashlib.sha256(actual).digest() != hashlib.sha256(content).digest():
            raise OnyxError(
                OnyxErrorCode.INTERNAL_ERROR,
                "Stored document failed its integrity check",
            )
        return file_id

    return save


@router.get("/status")
def status(_: User = Depends(require_word_user)) -> WordStatus:
    return WordStatus(enabled=_enabled())


@router.get("")
def list_documents(
    user: User = Depends(require_word_user), db_session: Session = Depends(get_session)
) -> list[DocumentSnapshot]:
    _require_enabled()
    return db.list_documents(db_session, user.id)


@router.post("")
def create_document(
    idempotency_key: Annotated[UUID, Header(alias="Idempotency-Key")],
    title: str = Form("Untitled document", max_length=255),
    file: UploadFile | None = File(None),
    user: User = Depends(require_word_user),
    db_session: Session = Depends(get_session),
) -> VersionResult:
    _require_enabled()
    title = _filename(title)
    content = blank_docx() if file is None else _upload(file)
    return db.create_document(
        db_session, user.id, title, content, idempotency_key, _store(user.id)
    )


@router.get("/{document_id}")
def get_document(
    document_id: UUID,
    user: User = Depends(require_word_user),
    db_session: Session = Depends(get_session),
) -> DocumentSnapshot:
    _require_enabled()
    return db.snapshot(db_session, user.id, document_id)


@router.get("/{document_id}/versions/{version_id}/content")
def get_content(
    document_id: UUID,
    version_id: UUID,
    user: User = Depends(require_word_user),
    db_session: Session = Depends(get_session),
) -> Response:
    _require_enabled()
    document, version = db.get_version(db_session, user.id, document_id, version_id)
    with get_default_file_store().read_file(version.file_id, mode="b") as source:
        content = source.read(MAX_DOCX_BYTES + 1)
    if (
        len(content) > MAX_DOCX_BYTES
        or hashlib.sha256(content).hexdigest() != version.content_hash
    ):
        raise OnyxError(
            OnyxErrorCode.INTERNAL_ERROR, "Stored document failed its integrity check"
        )
    filename = _filename(document.title)
    return Response(
        content,
        media_type=DOCX_MIME,
        headers={
            "Cache-Control": "private, no-store",
            "X-Content-Type-Options": "nosniff",
            "Content-Disposition": f"attachment; filename*=UTF-8''{quote(filename, safe='')}",
            "ETag": f'"{version.content_hash}"',
        },
    )


@router.post("/{document_id}/versions")
def save_version(
    document_id: UUID,
    idempotency_key: Annotated[UUID, Header(alias="Idempotency-Key")],
    expected_version: UUID = Form(),
    file: UploadFile = File(),
    user: User = Depends(require_word_user),
    db_session: Session = Depends(get_session),
) -> VersionResult:
    _require_enabled()
    # Check ownership before processing a potentially large document upload.
    db.get_document(db_session, user.id, document_id)
    content = _upload(file)
    return db.save_version(
        db_session,
        user.id,
        document_id,
        expected_version,
        content,
        idempotency_key,
        _store(user.id),
    )
