"""Tenant-session queries and atomic, owner-scoped Word version writes."""

import hashlib
import json
from collections.abc import Callable
from datetime import datetime, timezone
from typing import Literal, cast
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from onyx.configs.constants import FileOrigin
from onyx.db.models import FileRecord, WordDocument, WordDocumentVersion
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
from onyx.word_documents.contracts import DocumentSnapshot, VersionResult

StoreVersion = Callable[[UUID, bytes], str]


def is_private_word_file(db_session: Session, file_id: str) -> bool:
    return (
        db_session.scalar(
            select(FileRecord.file_id).where(
                FileRecord.file_id == file_id,
                FileRecord.file_origin == FileOrigin.ORGMESH_WORD,
            )
        )
        is not None
    )


def _fingerprint(*values: str) -> str:
    return hashlib.sha256(json.dumps(values, ensure_ascii=False).encode()).hexdigest()


def _result(document: WordDocument, version: WordDocumentVersion) -> VersionResult:
    return VersionResult(
        document_id=document.id,
        version_id=version.id,
        content_hash=version.content_hash,
        title=document.title,
        parent_version_id=version.parent_version_id,
        operation=cast(Literal["import", "manual"], version.operation),
    )


def get_document(
    db_session: Session, owner: UUID, document_id: UUID, *, lock: bool = False
) -> WordDocument:
    statement = select(WordDocument).where(
        WordDocument.id == document_id, WordDocument.user_id == owner
    )
    if lock:
        statement = statement.with_for_update().execution_options(
            populate_existing=True
        )
    document = db_session.scalar(statement)
    if document is None:
        raise OnyxError(OnyxErrorCode.NOT_FOUND, "Document not found")
    return document


def get_version(
    db_session: Session, owner: UUID, document_id: UUID, version_id: UUID
) -> tuple[WordDocument, WordDocumentVersion]:
    document = get_document(db_session, owner, document_id)
    version = db_session.scalar(
        select(WordDocumentVersion).where(
            WordDocumentVersion.id == version_id,
            WordDocumentVersion.document_id == document_id,
        )
    )
    if version is None:
        raise OnyxError(OnyxErrorCode.NOT_FOUND, "Version not found")
    return document, version


def snapshot(db_session: Session, owner: UUID, document_id: UUID) -> DocumentSnapshot:
    document = get_document(db_session, owner, document_id)
    _, version = get_version(
        db_session, owner, document_id, document.current_version_id
    )
    return DocumentSnapshot(**_result(document, version).model_dump())


def list_documents(db_session: Session, owner: UUID) -> list[DocumentSnapshot]:
    rows = db_session.execute(
        select(WordDocument, WordDocumentVersion)
        .join(
            WordDocumentVersion,
            WordDocumentVersion.id == WordDocument.current_version_id,
        )
        .where(WordDocument.user_id == owner)
        .order_by(WordDocument.updated_at.desc(), WordDocument.id.desc())
    )
    return [
        DocumentSnapshot(**_result(document, version).model_dump())
        for document, version in rows
    ]


def _creation_retry(
    db_session: Session, owner: UUID, key: UUID, request_hash: str
) -> VersionResult | None:
    document = db_session.scalar(
        select(WordDocument).where(
            WordDocument.user_id == owner, WordDocument.creation_key == key
        )
    )
    if document is None:
        return None
    if document.creation_hash != request_hash:
        raise OnyxError(
            OnyxErrorCode.CONFLICT, "Idempotency key was used for a different request"
        )
    version = db_session.scalar(
        select(WordDocumentVersion).where(
            WordDocumentVersion.document_id == document.id,
            WordDocumentVersion.operation == "import",
        )
    )
    if version is None:
        raise OnyxError(
            OnyxErrorCode.INTERNAL_ERROR, "Initial document version is unavailable"
        )
    return _result(document, version)


def create_document(
    db_session: Session,
    owner: UUID,
    title: str,
    content: bytes,
    key: UUID,
    store: StoreVersion,
) -> VersionResult:
    content_hash = hashlib.sha256(content).hexdigest()
    request_hash = _fingerprint(title, content_hash)
    previous = _creation_retry(db_session, owner, key, request_hash)
    if previous:
        return previous
    document_id, version_id = uuid4(), uuid4()
    # The file store commits its own session before this transaction references it.
    file_id = store(version_id, content)
    document = WordDocument(
        id=document_id,
        user_id=owner,
        title=title,
        current_version_id=version_id,
        creation_key=key,
        creation_hash=request_hash,
    )
    version = WordDocumentVersion(
        id=version_id,
        document_id=document_id,
        parent_version_id=None,
        file_id=file_id,
        content_hash=content_hash,
        created_by=owner,
        operation="import",
        idempotency_key=key,
        request_hash=request_hash,
    )
    db_session.add_all([document, version])
    try:
        db_session.commit()
    except IntegrityError:
        db_session.rollback()
        previous = _creation_retry(db_session, owner, key, request_hash)
        if previous:
            return previous
        raise
    return _result(document, version)


def save_version(
    db_session: Session,
    owner: UUID,
    document_id: UUID,
    expected_version: UUID,
    content: bytes,
    key: UUID,
    store: StoreVersion,
) -> VersionResult:
    document = get_document(db_session, owner, document_id, lock=True)
    content_hash = hashlib.sha256(content).hexdigest()
    request_hash = _fingerprint(str(expected_version), content_hash)
    previous = db_session.scalar(
        select(WordDocumentVersion).where(
            WordDocumentVersion.document_id == document_id,
            WordDocumentVersion.idempotency_key == key,
            WordDocumentVersion.operation == "manual",
        )
    )
    if previous is not None:
        if previous.request_hash != request_hash:
            raise OnyxError(
                OnyxErrorCode.CONFLICT,
                "Idempotency key was used for a different request",
            )
        return _result(document, previous)
    if document.current_version_id != expected_version:
        raise OnyxError(
            OnyxErrorCode.CONFLICT,
            "Document has a newer saved version",
            extra={"current_version_id": str(document.current_version_id)},
        )
    version_id = uuid4()
    file_id = store(version_id, content)
    version = WordDocumentVersion(
        id=version_id,
        document_id=document_id,
        parent_version_id=expected_version,
        file_id=file_id,
        content_hash=content_hash,
        created_by=owner,
        operation="manual",
        idempotency_key=key,
        request_hash=request_hash,
    )
    db_session.add(version)
    document.current_version_id = version_id
    document.updated_at = datetime.now(timezone.utc)
    db_session.commit()
    return _result(document, version)
