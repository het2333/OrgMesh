"""Word persistence contract tests; use the isolated runner without the app stack."""

import hashlib
from io import BytesIO
from types import SimpleNamespace
from uuid import uuid4
from zipfile import ZIP_DEFLATED, ZipFile, ZipInfo

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import (
    Column,
    Enum,
    MetaData,
    String,
    Table,
    Uuid,
    create_engine,
    event,
    select,
)
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool


def package(text: str = "hello", extra: dict[str, bytes] | None = None) -> bytes:
    parts = {
        "[Content_Types].xml": b'<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="xml" ContentType="application/xml"/><Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/></Types>',
        "_rels/.rels": b'<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/></Relationships>',
        "word/document.xml": f'<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body><w:p><w:r><w:t>{text}</w:t></w:r></w:p></w:body></w:document>'.encode(),
    }
    parts.update(extra or {})
    output = BytesIO()
    with ZipFile(output, "w", ZIP_DEFLATED) as archive:
        for name, data in parts.items():
            info = ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
            info.compress_type = ZIP_DEFLATED
            archive.writestr(info, data)
    return output.getvalue()


@pytest.fixture
def api(monkeypatch):
    from onyx.configs.constants import FileOrigin
    from onyx.db.models import WordDocument, WordDocumentVersion
    from onyx.error_handling.exceptions import OnyxError
    from onyx.server import word_documents as routes

    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    event.listen(
        engine, "connect", lambda conn, _: conn.execute("PRAGMA foreign_keys=ON")
    )
    metadata = MetaData()
    Table("user", metadata, Column("id", Uuid(), primary_key=True))
    Table(
        "file_record",
        metadata,
        Column("file_id", String, primary_key=True),
        Column("file_origin", Enum(FileOrigin, native_enum=False)),
    )
    WordDocument.__table__.to_metadata(metadata)
    WordDocumentVersion.__table__.to_metadata(metadata)
    metadata.create_all(engine)
    owner, other = uuid4(), uuid4()
    with engine.begin() as conn:
        conn.execute(metadata.tables["user"].insert(), [{"id": owner}, {"id": other}])
    blobs = {}

    class Store:
        fail = False

        def save_file(self, content, **kwargs):
            assert kwargs.get("db_session") is None, (
                "File store commits must not commit document transaction"
            )
            assert kwargs["file_origin"].value == "orgmesh_word"
            if self.fail:
                raise RuntimeError("simulated interrupted object write")
            file_id = kwargs["file_id"]
            assert file_id not in blobs, "Version objects are immutable"
            blobs[file_id] = content.read()
            return file_id

        def read_file(self, file_id, **_kwargs):
            return BytesIO(blobs[file_id])

    store = Store()
    monkeypatch.setattr(routes, "get_default_file_store", lambda: store)
    monkeypatch.setenv("ORGMESH_WORD_ENABLED", "true")
    active_user = SimpleNamespace(id=owner)

    def session():
        with Session(engine) as db:
            yield db

    app = FastAPI()
    from fastapi.responses import JSONResponse

    @app.exception_handler(OnyxError)
    async def error_handler(_, exc):
        return JSONResponse(
            status_code=exc.status_code,
            content={
                **(exc.extra or {}),
                "error_code": exc.error_code.code,
                "detail": exc.detail,
            },
        )

    app.include_router(routes.router)
    app.dependency_overrides[routes.require_word_user] = lambda: active_user
    app.dependency_overrides[routes.get_session] = session
    with TestClient(app) as client:
        yield SimpleNamespace(
            client=client,
            user=active_user,
            owner=owner,
            other=other,
            blobs=blobs,
            store=store,
            engine=engine,
            metadata=metadata,
            Document=WordDocument,
            Version=WordDocumentVersion,
        )


def create(api, data=None, key=None, title="Report"):
    return api.client.post(
        "/orgmesh/documents",
        data={"title": title},
        files={"file": ("report.docx", data)} if data is not None else None,
        headers={"Idempotency-Key": str(key or uuid4())},
    )


def save(api, doc, data, key=None, expected=None):
    return api.client.post(
        f"/orgmesh/documents/{doc['document_id']}/versions",
        data={"expected_version": expected or doc["version_id"]},
        files={"file": ("report.docx", data)},
        headers={"Idempotency-Key": str(key or uuid4())},
    )


def content(api, doc):
    return api.client.get(
        f"/orgmesh/documents/{doc['document_id']}/versions/{doc['version_id']}/content"
    )


def test_blank_create_is_valid_docx(api):
    from onyx.word_documents.validation import validate_docx

    response = create(api)
    assert response.status_code == 200, response.text
    doc = response.json()
    assert doc["operation"] == "import" and doc["parent_version_id"] is None
    assert doc["project_id"] is None
    raw = content(api, doc)
    assert raw.status_code == 200
    validate_docx(raw.content)
    assert doc["content_hash"] == hashlib.sha256(raw.content).hexdigest()
    assert b"word/document.xml" in raw.content


def test_import_save_reopen_and_old_bytes_remain_immutable(api):
    raw = package(extra={"word/media/image1.png": b"unchanged image bytes"})
    original = create(api, raw).json()
    assert content(api, original).content == raw
    changed = package("new text")
    saved = save(api, original, changed)
    assert saved.status_code == 200, saved.text
    updated = saved.json()
    assert updated["parent_version_id"] == original["version_id"]
    assert updated["operation"] == "manual"
    assert updated["content_hash"] == hashlib.sha256(changed).hexdigest()
    reopened = api.client.get(f"/orgmesh/documents/{original['document_id']}").json()
    assert reopened["version_id"] == updated["version_id"]
    assert content(api, updated).content == changed
    assert content(api, original).content == raw
    assert api.client.get("/orgmesh/documents").json() == [reopened]


def test_create_response_loss_retry_returns_original_version_after_later_save(api):
    key = uuid4()
    original = create(api, package(), key).json()
    save(api, original, package("changed"))
    retried = create(api, package(), key)
    assert retried.status_code == 200
    assert retried.json() == original
    assert len(api.blobs) == 2
    assert create(api, package("other"), key).status_code == 409
    assert create(api, package(), key, title="Different").status_code == 409


def test_blank_create_retry_is_deterministic(api):
    key = uuid4()
    assert create(api, key=key).json() == create(api, key=key).json()
    assert len(api.blobs) == 1


def test_save_response_loss_retry_precedes_version_check(api):
    original = create(api, package()).json()
    key = uuid4()
    saved = save(api, original, package("changed"), key)
    assert saved.status_code == 200
    assert save(api, original, package("changed"), key).json() == saved.json()
    assert len(api.blobs) == 2
    assert save(api, original, package("different"), key).status_code == 409
    assert save(api, saved.json(), package("changed"), key).status_code == 409


def test_stale_save_returns_current_version_without_writing(api):
    original = create(api, package()).json()
    updated = save(api, original, package("new")).json()
    stale = save(api, original, package("stale"))
    assert stale.status_code == 409
    assert stale.json()["current_version_id"] == updated["version_id"]
    assert len(api.blobs) == 2
    assert content(api, updated).content == package("new")


def test_wrong_owner_every_resource_is_404(api):
    original = create(api, package()).json()
    api.user.id = api.other
    assert api.client.get("/orgmesh/documents").json() == []
    assert (
        api.client.get(f"/orgmesh/documents/{original['document_id']}").status_code
        == 404
    )
    assert content(api, original).status_code == 404
    assert save(api, original, package()).status_code == 404
    assert len(api.blobs) == 1


def test_version_must_belong_to_requested_document(api):
    first = create(api, package()).json()
    second = create(api, package()).json()
    assert (
        content(api, {**first, "version_id": second["version_id"]}).status_code == 404
    )


def test_interrupted_object_write_keeps_current_version_and_retry_works(api):
    original = create(api, package()).json()
    key = uuid4()
    api.store.fail = True
    with pytest.raises(RuntimeError, match="interrupted"):
        save(api, original, package("new"), key)
    with Session(api.engine) as db:
        assert len(db.scalars(select(api.Version)).all()) == 1
    api.store.fail = False
    assert save(api, original, package("new"), key).status_code == 200


def test_feature_is_closed_by_default(api, monkeypatch):
    monkeypatch.delenv("ORGMESH_WORD_ENABLED")
    assert api.client.get("/orgmesh/documents/status").json() == {"enabled": False}
    assert api.client.get("/orgmesh/documents").status_code == 403
    assert create(api).status_code == 403
    assert api.blobs == {}


def test_writes_require_uuid_idempotency_key(api):
    assert api.client.post("/orgmesh/documents").status_code == 422
    assert (
        api.client.post(
            "/orgmesh/documents", headers={"Idempotency-Key": "invalid"}
        ).status_code
        == 422
    )
    assert api.blobs == {}


@pytest.mark.parametrize(
    "extra",
    [
        {"../escape.xml": b"x"},
        {"word\\bad.xml": b"x"},
        {"/absolute.xml": b"x"},
        {"word/%2e%2e/escape.xml": b"x"},
        {"word/vbaProject.bin": b"macro"},
        {
            "word/document.xml": b'<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body><w:altChunk/></w:body></w:document>'
        },
        {
            "word/_rels/document.xml.rels": b'<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="r1" Type="image" Target="https://example.com/a.png" TargetMode="External"/></Relationships>'
        },
        {
            "word/_rels/document.xml.rels": b'<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="r1" Type="image" Target="file:///etc/passwd"/></Relationships>'
        },
        {"word/evil.xml": b'<!DOCTYPE a [<!ENTITY x "expanded">]><a>&x;</a>'},
        {
            "word/evil.xml": '<!DOCTYPE a [<!ENTITY x "expanded">]><a>&x;</a>'.encode(
                "utf-16"
            )
        },
    ],
)
def test_rejects_unsafe_packages_before_storage(api, extra):
    response = create(api, package(extra=extra))
    assert response.status_code == 400, response.text
    assert api.blobs == {}


def test_rejects_non_docx_and_truncated_zip(api):
    assert create(api, b"not a docx").status_code == 400
    assert create(api, package()[:-10]).status_code == 400
    assert api.blobs == {}


def test_upload_size_is_bounded(api):
    assert create(api, b"a" * (20 * 1024 * 1024 + 1)).status_code == 413
    assert api.blobs == {}


def test_inflated_size_and_entry_count_are_bounded(monkeypatch):
    from onyx.error_handling.exceptions import OnyxError
    from onyx.word_documents import validation

    monkeypatch.setattr(validation, "MAX_INFLATED_BYTES", 1000)
    with pytest.raises(OnyxError) as exc:
        validation.validate_docx(package(extra={"word/big.txt": b"x" * 1001}))
    assert exc.value.status_code == 413
    monkeypatch.setattr(validation, "MAX_INFLATED_BYTES", 100 * 1024 * 1024)
    monkeypatch.setattr(validation, "MAX_ZIP_ENTRIES", 2)
    with pytest.raises(OnyxError) as exc:
        validation.validate_docx(package())
    assert exc.value.status_code == 413


def test_private_word_bytes_cannot_be_read_through_generic_chat_file(api):
    import ast
    from pathlib import Path

    from sqlalchemy import literal

    from onyx.configs.constants import FileOrigin
    from onyx.db.word_documents import is_private_word_file

    file_id = "orgmesh-word/private.docx"
    with api.engine.begin() as connection:
        connection.execute(
            api.metadata.tables["file_record"].insert(),
            {"file_id": file_id, "file_origin": FileOrigin.ORGMESH_WORD},
        )
    # Load the production ACL function and simulate an attacker-controlled chat reference.
    source = Path(__file__).resolve().parents[3] / "onyx/access/access.py"
    tree = ast.parse(source.read_text())
    declaration = next(
        node
        for node in tree.body
        if isinstance(node, ast.FunctionDef)
        and node.name == "user_can_access_chat_file"
    )
    namespace = {
        "User": SimpleNamespace,
        "Session": Session,
        "select": select,
        "is_private_word_file": is_private_word_file,
        "UserFile": SimpleNamespace(
            id=literal(1), file_id=literal(file_id), user_id=literal(str(api.owner))
        ),
    }
    exec(
        compile(ast.Module(body=[declaration], type_ignores=[]), str(source), "exec"),
        namespace,
    )
    with Session(api.engine) as db:
        assert (
            namespace["user_can_access_chat_file"](
                file_id, SimpleNamespace(id=str(api.owner)), db
            )
            is False
        )


def test_database_failure_does_not_advance_document_and_retry_works(api):
    original = create(api, package()).json()
    key = uuid4()

    def fail_commit(_):
        raise RuntimeError("simulated interrupted commit")

    event.listen(Session, "before_commit", fail_commit)
    try:
        with pytest.raises(RuntimeError, match="interrupted commit"):
            save(api, original, package("new"), key)
    finally:
        event.remove(Session, "before_commit", fail_commit)
    assert (
        api.client.get(f"/orgmesh/documents/{original['document_id']}").json()[
            "version_id"
        ]
        == original["version_id"]
    )
    assert save(api, original, package("new"), key).status_code == 200


def test_download_rejects_corrupted_stored_bytes(api):
    doc = create(api, package()).json()
    file_id = next(iter(api.blobs))
    api.blobs[file_id] = b"corrupt"
    assert content(api, doc).status_code == 500


def test_unauthenticated_requests_use_auth_dependency(api):
    from onyx.error_handling.error_codes import OnyxErrorCode
    from onyx.error_handling.exceptions import OnyxError
    from onyx.server import word_documents as routes

    def unauthenticated():
        raise OnyxError(OnyxErrorCode.UNAUTHENTICATED)

    api.client.app.dependency_overrides[routes.require_word_user] = unauthenticated
    assert api.client.get("/orgmesh/documents/status").status_code == 401
    assert api.client.get("/orgmesh/documents").status_code == 401
    assert create(api).status_code == 401


def test_duplicate_zip_paths_are_rejected(api):
    data = BytesIO(package())
    with ZipFile(data, "a") as archive:
        with pytest.warns(UserWarning, match="Duplicate name"):
            archive.writestr("word/document.xml", b"duplicate")
    assert create(api, data.getvalue()).status_code == 400


def test_idempotency_key_scope_separates_create_and_save(api):
    key = uuid4()
    original = create(api, package(), key).json()
    response = save(api, original, package("new"), key)
    assert response.status_code == 200


def test_migration_emits_postgresql_create_and_drop_sql():
    import importlib.util
    from io import StringIO
    from pathlib import Path

    from alembic.migration import MigrationContext
    from alembic.operations import Operations

    path = (
        Path(__file__).resolve().parents[3]
        / "alembic/versions/c71e9a2d4f60_add_owner_scoped_word_documents.py"
    )
    spec = importlib.util.spec_from_file_location("word_migration", path)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    output = StringIO()
    context = MigrationContext.configure(
        dialect_name="postgresql", opts={"as_sql": True, "output_buffer": output}
    )
    with Operations.context(context):
        migration.upgrade()
        migration.downgrade()
    sql = output.getvalue()
    assert "CREATE TABLE orgmesh_word_document" in sql
    assert "DEFERRABLE INITIALLY DEFERRED" in sql
    assert "UNIQUE (document_id, operation, idempotency_key)" in sql
    assert "DROP TABLE orgmesh_word_document_version" in sql


def test_rejects_entities_in_xml_parts_with_other_extensions(api):
    with ZipFile(BytesIO(package())) as source:
        types = source.read("[Content_Types].xml").replace(
            b"</Types>",
            b'<Default Extension="vml" ContentType="application/vnd.openxmlformats-officedocument.vmlDrawing"/></Types>',
        )
    response = create(
        api,
        package(
            extra={
                "[Content_Types].xml": types,
                "word/drawing.vml": b'<!DOCTYPE a [<!ENTITY x "expanded">]><a>&x;</a>',
            }
        ),
    )
    assert response.status_code == 400
    assert api.blobs == {}


def test_rejects_invalid_deflate_data(api):
    raw = bytearray(package())
    with ZipFile(BytesIO(raw)) as source:
        first = source.infolist()[0]
        start = (
            first.header_offset + 30 + len(first.filename.encode()) + len(first.extra)
        )
        raw[start : start + 2] = b"\xff\xff"
    assert create(api, bytes(raw)).status_code == 400
    assert api.blobs == {}


def test_object_integrity_is_checked_before_version_commit(api, monkeypatch):
    raw_read = api.store.read_file
    monkeypatch.setattr(
        api.store, "read_file", lambda *_args, **_kwargs: BytesIO(b"corrupt")
    )
    response = create(api, package())
    assert response.status_code == 500
    with Session(api.engine) as db:
        assert db.scalars(select(api.Document)).all() == []
    monkeypatch.setattr(api.store, "read_file", raw_read)


@pytest.mark.parametrize(
    ("title", "expected"),
    [
        ("Quarterly report", "Quarterly report.docx"),
        ("Report.DOCX", "Report.DOCX"),
        ("../folder\\report\r\n", "..folderreport.docx"),
        ("  ", "Untitled document.docx"),
    ],
)
def test_titles_are_safe_docx_filenames(api, title, expected):
    from urllib.parse import unquote

    doc = create(api, package(), title=title).json()
    assert doc["title"] == expected
    assert unquote(content(api, doc).headers["content-disposition"]).endswith(expected)


def test_blank_docx_matches_original_editor_compatibility_fixture():
    from pathlib import Path

    from onyx.word_documents.validation import blank_docx

    root = Path(__file__).resolve().parents[4]
    fixture = root / "vendor/genoffice/apps/docs/tests/fixtures/orgmesh-blank.docx"
    assert blank_docx() == fixture.read_bytes()
