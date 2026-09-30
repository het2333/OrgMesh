import json
from collections.abc import Iterator
from datetime import datetime, timezone
from typing import Any
from unittest.mock import patch

import pytest
import requests

from onyx.connectors.feishu.client import (
    FeishuAPIError,
    FeishuClient,
    trusted_feishu_url,
)
from onyx.connectors.feishu.connector import FeishuConnector, FeishuObject
from onyx.connectors.models import Document, SlimDocument


def response(payload: dict[str, Any], status: int = 200) -> requests.Response:
    result = requests.Response()
    result.status_code = status
    result._content = json.dumps(payload).encode()
    _ = result.content
    result.headers["Content-Type"] = "application/json"
    return result


def data_response(data: dict[str, Any]) -> requests.Response:
    return response({"code": 0, "data": data})


def make_client() -> FeishuClient:
    client = FeishuClient("app", "secret")
    client._token = "token"
    client._token_expires_at = float("inf")
    return client


def make_connector(**kwargs: Any) -> FeishuConnector:
    connector = FeishuConnector(
        tenant_url="https://company.feishu.cn", folder_tokens=["root"], **kwargs
    )
    connector.client = make_client()
    return connector


def doc(kind: str = "docx", token: str = "document") -> FeishuObject:
    return FeishuObject(
        token=token,
        kind=kind,
        title="Test document",
        url=f"https://company.feishu.cn/{kind}/{token}",
        modified_at=datetime.fromtimestamp(100, tz=timezone.utc),
        created_at=datetime.fromtimestamp(50, tz=timezone.utc),
    )


@pytest.mark.parametrize(
    "url",
    [
        "http://company.feishu.cn",
        "https://evil.test",
        "https://feishu.cn.evil.test",
        "https://localhost",
        "https://user@company.feishu.cn",
        "https://company.feishu.cn:8080",
    ],
)
def test_reject_untrusted_tenant_urls(url: str) -> None:
    with pytest.raises(ValueError):
        trusted_feishu_url(url)


def test_official_origin_timeout_and_no_redirects() -> None:
    client = make_client()
    with patch.object(
        client._session, "request", return_value=data_response({})
    ) as send:
        assert client.request("/open-apis/drive/v1/files") == {}
    assert send.call_args.args[1] == "https://open.feishu.cn/open-apis/drive/v1/files"
    assert send.call_args.kwargs["timeout"] == (5, 45)
    assert send.call_args.kwargs["allow_redirects"] is False
    with pytest.raises(ValueError):
        client.request("https://evil.test/open-apis/files")


def test_refresh_expired_api_token() -> None:
    client = make_client()
    results = [
        response({"code": 99991663}),
        response({"code": 0, "tenant_access_token": "new", "expire": 7200}),
        data_response({"files": []}),
    ]
    with patch.object(client._session, "request", side_effect=results) as send:
        assert client.request("/open-apis/drive/v1/files") == {"files": []}
    assert send.call_args.kwargs["headers"]["Authorization"] == "Bearer new"


def test_retry_rate_limit() -> None:
    client = make_client()
    with (
        patch.object(
            client._session,
            "request",
            side_effect=[response({}, 429), data_response({})],
        ) as send,
        patch("onyx.connectors.feishu.client.time.sleep"),
    ):
        assert client.request("/open-apis/drive/v1/files") == {}
    assert send.call_count == 2


def test_pagination_collects_all_pages_and_rejects_cycles() -> None:
    client = make_client()
    pages = [
        {"items": [{"id": "first"}], "has_more": True, "page_token": "p2"},
        {"items": [{"id": "second"}], "has_more": False},
    ]
    with patch.object(client, "request", side_effect=pages) as request:
        assert list(client.iterate("/open-apis/wiki/v2/spaces")) == [
            {"id": "first"},
            {"id": "second"},
        ]
    assert request.call_args.kwargs["params"]["page_token"] == "p2"
    with patch.object(client, "request", side_effect=[pages[0], pages[0]]):
        with pytest.raises(FeishuAPIError, match="repeated"):
            list(client.iterate("/open-apis/wiki/v2/spaces"))


def test_permission_mapping_is_private_and_excludes_unsupported_members() -> None:
    connector = make_connector()
    members = {
        "items": [
            {"member_type": "openid", "member_id": "ou_alice", "perm": "view"},
            {"member_type": "email", "member_id": "BOB@EXAMPLE.COM", "perm": "edit"},
            {"member_type": "opendepartmentid", "member_id": "od_team", "perm": "view"},
            {"member_type": "openchat", "member_id": "oc_team", "perm": "view"},
            {"member_type": "wikispaceid", "member_id": "space", "perm": "view"},
            {"member_type": "email", "member_id": "denied@example.com", "perm": "none"},
        ]
    }
    with patch.object(
        connector._client(),
        "request",
        side_effect=[members, {"user": {"email": "Alice@Example.com"}}],
    ):
        access = connector._permissions(doc()).access
    assert access.external_user_emails == {"alice@example.com", "bob@example.com"}
    assert access.external_user_group_ids == {"feishu:department:od_team"}
    assert access.is_public is False


def test_resolved_user_acl_prefers_enterprise_email() -> None:
    connector = make_connector()
    with patch.object(
        connector._client(),
        "request",
        return_value={
            "user": {
                "enterprise_email": "Worker@Company.com",
                "email": "personal@example.com",
            }
        },
    ):
        assert connector._resolve_email("ou_worker", "open_id") == "worker@company.com"


def test_acl_freshness_precedes_contact_identity_resolution() -> None:
    connector = make_connector()
    contact_lookup_started: list[float] = []

    def request(
        path: str, *, params: dict[str, str | int] | None = None
    ) -> dict[str, Any]:
        assert params is not None
        if "/permissions/" in path:
            return {
                "items": [
                    {"member_type": "openid", "member_id": "ou_worker", "perm": "view"}
                ]
            }
        contact_lookup_started.append(datetime.now(timezone.utc).timestamp())
        return {"user": {"enterprise_email": "worker@company.com"}}

    with patch.object(connector._client(), "request", side_effect=request):
        permissions = connector._permissions(doc())
    assert permissions.checked_at <= contact_lookup_started[0]
    assert permissions.access.external_user_emails == {"worker@company.com"}


def test_acl_freshness_records_fetch_time_before_content_download() -> None:
    connector = make_connector()
    started = datetime.now(timezone.utc).timestamp()
    observed_fetch_time: list[float] = []

    def content(obj: FeishuObject) -> str:
        assert obj.token == "document"
        observed_fetch_time.append(datetime.now(timezone.utc).timestamp())
        return "content"

    with (
        patch.object(connector, "_objects", return_value=iter([doc()])),
        patch.object(connector._client(), "request", return_value={"items": []}),
        patch.object(connector, "_text", side_effect=content),
    ):
        indexed = list(connector.load_from_state())[0][0]
    assert isinstance(indexed, Document)
    assert isinstance(indexed.additional_info, dict)
    checked_at = indexed.additional_info["orgmesh_acl_checked_at"]
    assert isinstance(checked_at, float)
    assert started <= checked_at <= observed_fetch_time[0]


def test_drive_next_page_token_is_used_for_complete_enumeration() -> None:
    client = make_client()
    pages = [
        {"files": [{"token": "first"}], "has_more": True, "next_page_token": "next"},
        {"files": [{"token": "second"}], "has_more": False},
    ]
    with patch.object(client, "request", side_effect=pages):
        assert list(client.iterate("/open-apis/drive/v1/files", key="files")) == [
            {"token": "first"},
            {"token": "second"},
        ]


def test_permission_failure_stops_content_retrieval() -> None:
    connector = make_connector()
    with (
        patch.object(connector, "_objects", return_value=iter([doc()])),
        patch.object(
            connector._client(), "request", side_effect=FeishuAPIError("denied")
        ),
        patch.object(connector, "_text") as text,
    ):
        with pytest.raises(FeishuAPIError):
            list(connector.poll_source(0, 200))
    text.assert_not_called()


def test_missing_permission_list_is_an_error() -> None:
    connector = make_connector()
    with patch.object(connector._client(), "request", return_value={}):
        with pytest.raises(FeishuAPIError):
            connector._permissions(doc())


def test_unchanged_docs_still_refresh_acl_with_original_timestamp() -> None:
    connector = make_connector()
    with (
        patch.object(connector, "_objects", return_value=iter([doc()])),
        patch.object(connector._client(), "request", return_value={"items": []}),
        patch.object(connector, "_text", return_value="content"),
    ):
        batches = list(connector.poll_source(200, 300))
    indexed = batches[0][0]
    assert isinstance(indexed, Document)
    assert indexed.doc_updated_at == datetime.fromtimestamp(100, tz=timezone.utc)
    assert indexed.sections[0].link == doc().url
    assert indexed.external_access is not None
    assert indexed.external_access.is_public is False


def test_drive_recursive_and_full_slim_deletion_enumeration() -> None:
    connector = make_connector(include_files=False)

    def files(
        path: str,
        key: str = "items",
        params: dict[str, str | int] | None = None,
        page_size: int = 100,
    ) -> Iterator[dict[str, Any]]:
        assert path == "/open-apis/drive/v1/files"
        assert page_size == 200
        assert key == "files"
        assert params is not None
        if params["folder_token"] == "root":
            yield {"token": "child", "type": "folder", "name": "Folder"}
            yield {
                "token": "one",
                "type": "docx",
                "name": "One",
                "modified_time": "100",
                "url": "https://company.feishu.cn/docx/one",
            }
            yield {"token": "file", "type": "file", "name": "Omitted.pdf"}
        else:
            yield {"token": "two", "type": "doc", "name": "Two"}

    with patch.object(connector._client(), "iterate", side_effect=files):
        identifiers = [
            item.id
            for batch in connector.retrieve_all_slim_docs(999, 1000)
            for item in batch
            if isinstance(item, SlimDocument)
        ]
    assert identifiers == ["feishu:docx:one", "feishu:doc:two"]
    with patch.object(connector._client(), "iterate", return_value=iter([])):
        assert list(connector.retrieve_all_slim_docs()) == []


def test_wiki_children_keep_original_links_and_stable_ids() -> None:
    connector = FeishuConnector("https://company.feishu.cn", wiki_space_ids=["space"])
    connector.client = make_client()
    nodes = [
        {
            "node_token": "parent",
            "obj_token": "doc",
            "obj_type": "docx",
            "title": "One",
            "has_child": True,
            "url": "https://company.feishu.cn/wiki/parent",
        },
        {
            "node_token": "leaf",
            "obj_token": "sheet",
            "obj_type": "sheet",
            "title": "Two",
            "has_child": False,
        },
    ]
    with patch.object(
        connector._client(), "iterate", side_effect=[iter([nodes[0]]), iter([nodes[1]])]
    ):
        objects = list(connector._objects())
    assert [obj.document_id for obj in objects] == [
        "feishu:docx:doc",
        "feishu:sheet:sheet",
    ]
    assert objects[0].url == "https://company.feishu.cn/wiki/parent"


def test_advanced_table_denies_container_access_without_reading_rows() -> None:
    connector = make_connector()
    with (
        patch.object(connector, "_objects", return_value=iter([doc("bitable")])),
        patch.object(
            connector._client(),
            "request",
            side_effect=[
                {
                    "items": [
                        {
                            "member_type": "email",
                            "member_id": "reader@example.com",
                            "perm": "view",
                        }
                    ]
                },
                {"app": {"is_advanced": True}},
            ],
        ),
        patch.object(connector, "_text") as text,
    ):
        indexed = list(connector.load_from_state())[0][0]
    assert isinstance(indexed, Document)
    assert indexed.external_access is not None
    assert indexed.external_access.num_entries == 0
    assert indexed.external_access.is_public is False
    text.assert_not_called()


def test_docx_uses_official_raw_content_api() -> None:
    connector = make_connector()
    with patch.object(
        connector._client(),
        "request",
        return_value={"content": "A paragraph\nCell value"},
    ) as request:
        assert connector._text(doc()) == "A paragraph\nCell value"
    request.assert_called_once_with("/open-apis/docx/v1/documents/document/raw_content")


def test_table_records_include_all_pages_and_field_names() -> None:
    connector = make_connector()
    with patch.object(
        connector._client(),
        "iterate",
        side_effect=[
            iter([{"table_id": "table", "name": "People"}]),
            iter(
                [
                    {"fields": {"Name": "Alice", "Age": 30}},
                    {"fields": {"Name": "Bob", "Age": 31}},
                ]
            ),
        ],
    ):
        text = connector._bitable_text("app")
    assert "People" in text and '"Name": "Alice"' in text and '"Name": "Bob"' in text


def test_sheet_values_are_read_in_bounded_ranges() -> None:
    connector = make_connector()
    results = [
        {
            "sheets": [
                {
                    "sheet_id": "sheet",
                    "title": "Budget",
                    "grid_properties": {"row_count": 2, "column_count": 2},
                }
            ]
        },
        {"valueRange": {"values": [["Name", "Value"], ["Cost", 42]]}},
    ]
    with patch.object(connector._client(), "request", side_effect=results) as request:
        text = connector._sheet_text("token")
    assert "Cost,42" in text
    assert request.call_args.args[0].endswith("/values/sheet!A1:B2")


def test_native_factory_registration() -> None:
    from onyx.configs.constants import DocumentSource
    from onyx.connectors.registry import CONNECTOR_CLASS_MAP

    assert CONNECTOR_CLASS_MAP[DocumentSource.FEISHU].class_name == "FeishuConnector"


def test_uploaded_text_uses_native_file_parser() -> None:
    connector = make_connector()
    file = FeishuObject(
        token="upload",
        kind="file",
        title="note.txt",
        url="https://company.feishu.cn/file/upload",
        modified_at=None,
        created_at=None,
    )
    with patch.object(
        connector._client(),
        "download_file",
        return_value="飞书文件\nSecond line".encode(),
    ):
        text = connector._text(file)
    assert "飞书文件" in text and "Second line" in text


def test_download_is_bounded_and_never_redirected() -> None:
    client = make_client()
    binary = requests.Response()
    binary.status_code = 200
    binary._content = b"abcd"
    _ = binary.content
    binary.headers["Content-Type"] = "application/octet-stream"
    with (
        patch.object(client._session, "request", return_value=binary) as send,
        patch("onyx.connectors.feishu.client.MAX_DOWNLOAD_BYTES", 3),
    ):
        with pytest.raises(FeishuAPIError, match="limit"):
            client.download_file("file")
    assert send.call_args.kwargs["allow_redirects"] is False


def test_timeout_retries_are_finite() -> None:
    client = make_client()
    with (
        patch.object(client._session, "request", side_effect=requests.Timeout) as send,
        patch("onyx.connectors.feishu.client.time.sleep"),
    ):
        with pytest.raises(FeishuAPIError, match="timed out"):
            client.request("/open-apis/drive/v1/files")
    assert send.call_count == 5


def test_native_pruning_rejects_partial_feishu_enumeration() -> None:
    from onyx.background.celery.celery_utils import extract_ids_from_runnable_connector

    connector = make_connector(batch_size=1)

    def objects() -> Iterator[FeishuObject]:
        yield doc(token="first")
        raise FeishuAPIError("Second scope failed.")

    with patch.object(connector, "_objects", side_effect=objects):
        with pytest.raises(FeishuAPIError, match="Second scope"):
            extract_ids_from_runnable_connector(connector, connector_type="feishu")


def test_native_pruning_uses_complete_slim_success_without_content_fetch() -> None:
    from onyx.background.celery.celery_utils import extract_ids_from_runnable_connector

    connector = make_connector(batch_size=1)
    with (
        patch.object(
            connector,
            "_objects",
            return_value=iter([doc(token="first"), doc(token="second")]),
        ),
        patch.object(connector, "poll_source") as poll,
        patch.object(connector, "_permissions") as permissions,
    ):
        result = extract_ids_from_runnable_connector(connector, connector_type="feishu")
    assert set(result.raw_id_to_parent) == {"feishu:docx:first", "feishu:docx:second"}
    poll.assert_not_called()
    permissions.assert_not_called()
