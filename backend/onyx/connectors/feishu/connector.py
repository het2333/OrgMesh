"""Feishu Drive and Wiki connector with source permissions on every poll."""

import csv
import io
import json
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlsplit

from onyx.access.models import ExternalAccess
from onyx.configs.app_configs import INDEX_BATCH_SIZE
from onyx.configs.constants import DocumentSource
from onyx.connectors.exceptions import ConnectorValidationError
from onyx.connectors.feishu.client import (
    FeishuAPIError,
    FeishuClient,
    api_identifier,
    require_items,
    require_object,
    trusted_feishu_url,
)
from onyx.connectors.interfaces import (
    GenerateDocumentsOutput,
    GenerateSlimDocumentOutput,
    LoadConnector,
    PollConnector,
    SecondsSinceUnixEpoch,
    SlimConnector,
)
from onyx.connectors.models import (
    ConnectorMissingCredentialError,
    Document,
    HierarchyNode,
    SlimDocument,
    TextSection,
)
from onyx.indexing.indexing_heartbeat import IndexingHeartbeatInterface

SUPPORTED_TYPES = {"doc", "docx", "sheet", "bitable", "file"}
READ_PERMISSIONS = {"view", "edit", "full_access"}
USER_ID_TYPES = {"openid": "open_id", "unionid": "union_id", "userid": "user_id"}
FILE_EXTENSIONS = {
    ".txt",
    ".md",
    ".csv",
    ".tsv",
    ".pdf",
    ".docx",
    ".xlsx",
    ".pptx",
    ".html",
}
MAX_SHEET_CELLS = 1_000_000


def _required_string(data: dict[str, Any], key: str) -> str:
    value = data.get(key)
    if not isinstance(value, str) or not value:
        raise FeishuAPIError(f"Feishu response has no {key}.")
    return value


def _timestamp(value: Any) -> datetime | None:
    if value is None or value == "":
        return None
    try:
        seconds = float(value)
    except (TypeError, ValueError) as exc:
        raise FeishuAPIError("Feishu returned an invalid document timestamp.") from exc
    if seconds > 10_000_000_000:
        seconds /= 1000
    return datetime.fromtimestamp(seconds, tz=timezone.utc)


def _csv_rows(rows: list[list[Any]]) -> str:
    output = io.StringIO()
    writer = csv.writer(output)
    for row in rows:
        writer.writerow(
            json.dumps(cell, ensure_ascii=False)
            if isinstance(cell, (dict, list))
            else cell
            for cell in row
        )
    return output.getvalue()


def _column_name(count: int) -> str:
    name = ""
    while count:
        count, remainder = divmod(count - 1, 26)
        name = chr(65 + remainder) + name
    return name


@dataclass(frozen=True)
class FeishuObject:
    token: str
    kind: str
    title: str
    url: str
    modified_at: datetime | None
    created_at: datetime | None
    owner_id: str | None = None

    @property
    def document_id(self) -> str:
        return f"feishu:{self.kind}:{self.token}"


@dataclass(frozen=True)
class FeishuPermissions:
    access: ExternalAccess
    checked_at: float


class FeishuConnector(LoadConnector, PollConnector, SlimConnector):
    def __init__(
        self,
        tenant_url: str,
        folder_tokens: list[str] | None = None,
        wiki_space_ids: list[str] | None = None,
        include_files: bool = True,
        batch_size: int = INDEX_BATCH_SIZE,
    ) -> None:
        self.tenant_url = trusted_feishu_url(tenant_url)
        parsed = urlsplit(self.tenant_url)
        if parsed.path not in ("", "/") or parsed.query or parsed.fragment:
            raise ValueError("Feishu tenant URL must contain only the HTTPS origin.")
        self.folder_tokens = [api_identifier(token) for token in folder_tokens or []]
        self.wiki_space_ids = [api_identifier(space) for space in wiki_space_ids or []]
        if not self.folder_tokens and not self.wiki_space_ids:
            raise ValueError("Add at least one Feishu folder token or wiki space ID.")
        if batch_size < 1:
            raise ValueError("Feishu batch size must be positive.")
        self.include_files = include_files
        self.batch_size = batch_size
        self.client: FeishuClient | None = None
        self._user_emails: dict[tuple[str, str], str | None] = {}

    def load_credentials(self, credentials: dict[str, Any]) -> dict[str, Any] | None:
        app_id = credentials.get("feishu_app_id")
        app_secret = credentials.get("feishu_app_secret")
        if not isinstance(app_id, str) or not isinstance(app_secret, str):
            raise ConnectorValidationError("Feishu App ID and App Secret are required.")
        self.client = FeishuClient(app_id, app_secret)
        return None

    def _client(self) -> FeishuClient:
        if self.client is None:
            raise ConnectorMissingCredentialError("Feishu")
        return self.client

    def _supported(self, kind: str, title: str) -> bool:
        if kind not in SUPPORTED_TYPES:
            return False
        if kind == "file":
            return self.include_files and any(
                title.lower().endswith(ext) for ext in FILE_EXTENSIONS
            )
        return True

    def _source_link(self, value: str | None, kind: str, token: str) -> str:
        if value:
            return trusted_feishu_url(value)
        path = {"doc": "docs", "sheet": "sheets", "bitable": "base"}.get(kind, kind)
        return f"{self.tenant_url}/{path}/{token}"

    def _drive_objects(self) -> Iterator[FeishuObject]:
        client = self._client()
        pending = list(self.folder_tokens)
        visited: set[str] = set()
        while pending:
            folder = pending.pop()
            if folder in visited:
                continue
            visited.add(folder)
            for item in client.iterate(
                "/open-apis/drive/v1/files",
                key="files",
                params={"folder_token": folder, "user_id_type": "open_id"},
                page_size=200,
            ):
                kind = _required_string(item, "type")
                token = api_identifier(_required_string(item, "token"))
                title = _required_string(item, "name")
                if kind == "folder":
                    pending.append(token)
                elif self._supported(kind, title):
                    yield FeishuObject(
                        token=token,
                        kind=kind,
                        title=title,
                        url=self._source_link(item.get("url"), kind, token),
                        modified_at=_timestamp(item.get("modified_time")),
                        created_at=_timestamp(item.get("created_time")),
                        owner_id=item.get("owner_id"),
                    )

    def _wiki_objects(self) -> Iterator[FeishuObject]:
        client = self._client()
        for space in self.wiki_space_ids:
            pending: list[str | None] = [None]
            visited: set[str | None] = set()
            while pending:
                parent = pending.pop()
                if parent in visited:
                    continue
                visited.add(parent)
                params: dict[str, str | int] = {}
                if parent:
                    params["parent_node_token"] = parent
                for node in client.iterate(
                    f"/open-apis/wiki/v2/spaces/{space}/nodes",
                    params=params,
                    page_size=50,
                ):
                    node_token = api_identifier(_required_string(node, "node_token"))
                    if node.get("has_child") is True:
                        pending.append(node_token)
                    kind = _required_string(node, "obj_type")
                    title = _required_string(node, "title")
                    if not self._supported(kind, title):
                        continue
                    token = api_identifier(_required_string(node, "obj_token"))
                    yield FeishuObject(
                        token=token,
                        kind=kind,
                        title=title,
                        url=self._source_link(node.get("url"), "wiki", node_token),
                        modified_at=_timestamp(node.get("obj_edit_time")),
                        created_at=_timestamp(node.get("obj_create_time")),
                        owner_id=node.get("owner"),
                    )

    def _objects(self) -> Iterator[FeishuObject]:
        seen: set[str] = set()
        for objects in (self._wiki_objects(), self._drive_objects()):
            for obj in objects:
                if obj.document_id not in seen:
                    seen.add(obj.document_id)
                    yield obj

    def _resolve_email(self, member_id: str, user_id_type: str) -> str | None:
        key = (user_id_type, member_id)
        if key not in self._user_emails:
            data = self._client().request(
                f"/open-apis/contact/v3/users/{api_identifier(member_id)}",
                params={"user_id_type": user_id_type},
            )
            user = require_object(data.get("user"))
            email = user.get("enterprise_email") or user.get("email")
            self._user_emails[key] = (
                email.strip().lower()
                if isinstance(email, str) and "@" in email
                else None
            )
        return self._user_emails[key]

    def _permissions(self, obj: FeishuObject) -> FeishuPermissions:
        # API errors propagate. Unknown member types never grant access.
        data = self._client().request(
            f"/open-apis/drive/v1/permissions/{obj.token}/members",
            params={"type": obj.kind, "fields": "*"},
        )
        checked_at = datetime.now(timezone.utc).timestamp()
        emails: set[str] = set()
        departments: set[str] = set()
        for member in require_items(data, "items"):
            if member.get("perm") not in READ_PERMISSIONS:
                continue
            member_type = _required_string(member, "member_type")
            member_id = _required_string(member, "member_id")
            if member_type == "email" and "@" in member_id:
                emails.add(member_id.strip().lower())
            elif member_type in USER_ID_TYPES:
                email = self._resolve_email(member_id, USER_ID_TYPES[member_type])
                if email:
                    emails.add(email)
            elif member_type == "opendepartmentid":
                departments.add(f"feishu:department:{api_identifier(member_id)}")
        if obj.owner_id:
            owner_email = self._resolve_email(obj.owner_id, "open_id")
            if owner_email:
                emails.add(owner_email)
        access = ExternalAccess(emails, departments, is_public=False)
        if access.num_entries > ExternalAccess.MAX_NUM_ENTRIES:
            raise FeishuAPIError(
                "Feishu document permissions exceed the supported limit."
            )
        return FeishuPermissions(access=access, checked_at=checked_at)

    def _sheet_text(self, token: str) -> str:
        client = self._client()
        data = client.request(f"/open-apis/sheets/v3/spreadsheets/{token}/sheets/query")
        texts: list[str] = []
        for sheet in require_items(data, "sheets"):
            sheet_id = api_identifier(_required_string(sheet, "sheet_id"))
            grid = require_object(sheet.get("grid_properties"))
            rows, columns = grid.get("row_count"), grid.get("column_count")
            if (
                not isinstance(rows, int)
                or not isinstance(columns, int)
                or rows < 0
                or columns < 0
            ):
                raise FeishuAPIError("Feishu sheet has invalid dimensions.")
            if rows * columns > MAX_SHEET_CELLS:
                raise FeishuAPIError("Feishu sheet exceeds the supported cell limit.")
            texts.append(_required_string(sheet, "title"))
            if not rows or not columns:
                continue
            # The values API limits each request to 5,000 rows and 100 columns.
            for column_start in range(1, columns + 1, 100):
                column_end = min(column_start + 99, columns)
                for row_start in range(1, rows + 1, 5000):
                    row_end = min(row_start + 4999, rows)
                    cell_range = f"{sheet_id}!{_column_name(column_start)}{row_start}:{_column_name(column_end)}{row_end}"
                    values = client.request(
                        f"/open-apis/sheets/v2/spreadsheets/{token}/values/{cell_range}",
                        params={"valueRenderOption": "ToString"},
                    )
                    value_range = require_object(values.get("valueRange"))
                    cell_rows = value_range.get("values")
                    if not isinstance(cell_rows, list) or not all(
                        isinstance(row, list) for row in cell_rows
                    ):
                        raise FeishuAPIError("Feishu sheet has invalid cell values.")
                    texts.append(_csv_rows(cell_rows))
        return "\n\n".join(texts)

    def _bitable_text(self, token: str) -> str:
        client = self._client()
        texts: list[str] = []
        for table in client.iterate(f"/open-apis/bitable/v1/apps/{token}/tables"):
            table_id = api_identifier(_required_string(table, "table_id"))
            texts.append(_required_string(table, "name"))
            for record in client.iterate(
                f"/open-apis/bitable/v1/apps/{token}/tables/{table_id}/records",
                page_size=500,
            ):
                fields = require_object(record.get("fields"))
                texts.append(json.dumps(fields, ensure_ascii=False, sort_keys=True))
        return "\n\n".join(texts)

    def _text(self, obj: FeishuObject) -> str:
        client = self._client()
        if obj.kind in {"doc", "docx"}:
            prefix = "docx/v1/documents" if obj.kind == "docx" else "doc/v2"
            data = client.request(f"/open-apis/{prefix}/{obj.token}/raw_content")
            content = data.get("content")
            if not isinstance(content, str):
                raise FeishuAPIError("Feishu document has no text content.")
            return content
        if obj.kind == "sheet":
            return self._sheet_text(obj.token)
        if obj.kind == "bitable":
            return self._bitable_text(obj.token)
        # Keep heavy file parsers out of directory and document-only imports.
        from onyx.file_processing.extract_file_text import extract_file_text_locally

        return extract_file_text_locally(
            io.BytesIO(client.download_file(obj.token)),
            file_name=obj.title,
        )

    def load_from_state(self) -> GenerateDocumentsOutput:
        return self.poll_source(None, None)

    def poll_source(
        self, start: SecondsSinceUnixEpoch | None, end: SecondsSinceUnixEpoch | None
    ) -> GenerateDocumentsOutput:
        _ = start, end
        self._user_emails.clear()
        batch: list[Document | HierarchyNode] = []
        for obj in self._objects():
            permissions = self._permissions(obj)
            access = permissions.access
            # Advanced Bitable roles restrict rows and columns. Container ACLs are insufficient.
            advanced = False
            if obj.kind == "bitable":
                app = require_object(
                    self._client()
                    .request(f"/open-apis/bitable/v1/apps/{obj.token}")
                    .get("app")
                )
                advanced = app.get("is_advanced") is not False
                if advanced:
                    access = ExternalAccess.empty()
            # ACL changes do not reliably update source timestamps. The indexing pipeline
            # applies these ACLs before its timestamp and content deduplication checks.
            batch.append(
                Document(
                    id=obj.document_id,
                    source=DocumentSource.FEISHU,
                    semantic_identifier=obj.title,
                    title=obj.title,
                    sections=[
                        TextSection(
                            link=obj.url, text="" if advanced else self._text(obj)
                        )
                    ],
                    doc_updated_at=obj.modified_at,
                    doc_created_at=obj.created_at,
                    metadata={"type": obj.kind, "source_url": obj.url},
                    external_access=access,
                    additional_info={"orgmesh_acl_checked_at": permissions.checked_at},
                )
            )
            if len(batch) >= self.batch_size:
                yield batch
                batch = []
        if batch:
            yield batch

    def retrieve_all_slim_docs(
        self,
        start: SecondsSinceUnixEpoch | None = None,
        end: SecondsSinceUnixEpoch | None = None,
        callback: IndexingHeartbeatInterface | None = None,
    ) -> GenerateSlimDocumentOutput:
        # Pruning must enumerate the complete scope, irrespective of poll timestamps.
        _ = start, end
        batch: list[SlimDocument | HierarchyNode] = []
        for obj in self._objects():
            if callback and callback.should_stop():
                raise RuntimeError("Feishu enumeration was stopped before completion.")
            batch.append(
                SlimDocument(id=obj.document_id, doc_created_at=obj.created_at)
            )
            if len(batch) >= self.batch_size:
                if callback:
                    callback.progress("feishu-slim", len(batch))
                yield batch
                batch = []
        if batch:
            yield batch

    def validate_connector_settings(self) -> None:
        client = self._client()
        client.refresh_token()
        # Validate every configured scope. A successful first scope cannot mask invalid later scopes.
        for folder in self.folder_tokens:
            client.request(
                "/open-apis/drive/v1/files",
                params={"folder_token": folder, "page_size": 1},
            )
        for space in self.wiki_space_ids:
            client.request(
                f"/open-apis/wiki/v2/spaces/{space}/nodes", params={"page_size": 1}
            )
