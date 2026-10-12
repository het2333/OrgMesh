"""Daily usage values stay exact at the private service boundary."""

import json
from datetime import datetime, timedelta, timezone

import pytest
from pydantic import ValidationError

from onyx.orgmesh_enterprise.models import (
    TrustedIdentity,
    UsageQuery,
    decode_request,
    decode_response,
)


def test_usage_query_selects_current_daily_bucket() -> None:
    day = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    query = UsageQuery(start=day, end=day + timedelta(days=1))
    assert query.start == day
    with pytest.raises(ValidationError):
        UsageQuery(start=day + timedelta(seconds=1), end=day + timedelta(days=1))
    with pytest.raises(ValidationError):
        UsageQuery(start=day - timedelta(days=90), end=day + timedelta(days=1))


def test_producer_identity_is_operation_scoped() -> None:
    now = datetime.now(timezone.utc)
    identity = {
        "version": 1,
        "tenant_id": "public",
        "actor_kind": "producer",
        "user_id": "",
        "operation": "usage.begin",
        "request_id": "11111111-1111-4111-8111-111111111111",
        "audience": "orgmesh-enterprise/v1",
        "issued_at": now.isoformat(),
        "expires_at": (now + timedelta(seconds=5)).isoformat(),
    }
    assert (
        TrustedIdentity.model_validate_json(json.dumps(identity)).operation
        == "usage.begin"
    )
    identity["operation"] = "usage.summary"
    with pytest.raises(ValidationError):
        TrustedIdentity.model_validate_json(json.dumps(identity))
    identity.update(
        actor_kind="user",
        user_id="11111111-1111-4111-8111-111111111111",
        operation="usage.begin",
    )
    with pytest.raises(ValidationError):
        TrustedIdentity.model_validate_json(json.dumps(identity))


def test_waiting_response_is_explicit_and_cannot_stage() -> None:
    lease = {
        "status": "waiting",
        "revision": 0,
        "activated_at": "2026-10-12T12:00:00Z",
        "collection_start": "2026-10-13T00:00:00Z",
        "coverage": None,
        "expires_at": None,
    }
    response = decode_response(
        json.dumps({"operation": "usage.begin", "lease": lease}).encode()
    )
    assert response.lease.coverage is None
    lease["revision"] = 1
    with pytest.raises(ValueError):
        decode_response(
            json.dumps({"operation": "usage.begin", "lease": lease}).encode()
        )


def test_summary_rejects_missing_metadata_and_float_money() -> None:
    with pytest.raises(ValueError):
        decode_response(
            b'{"operation":"usage.summary","summary":{"status":"unavailable"}}'
        )


def test_snapshot_request_rejects_unknown_fields() -> None:
    with pytest.raises(ValueError):
        decode_request(
            b'{"operation":"usage.begin","coverage":{"from":"2026-10-12T00:00:00Z","to":"2026-10-13T00:00:00Z","tenant_id":"other"}}'
        )


def test_shared_digest_fixture_and_named_wire_models() -> None:
    import hashlib
    import struct
    from pathlib import Path

    import jsonschema

    from onyx.orgmesh_enterprise.models import (
        SnapshotBatch,
        SnapshotLease,
        SnapshotManifest,
    )

    root = Path(__file__).resolve().parents[4] / "contracts/orgmesh-enterprise"
    fixture = json.loads((root / "fixtures/usage-digest.json").read_text())
    batch = fixture["batch"]
    SnapshotBatch.model_validate_json(json.dumps(batch))
    SnapshotLease.model_validate_json(json.dumps(fixture["lease"]))
    SnapshotManifest.model_validate_json(json.dumps(fixture["manifest"]))

    def field(value: object) -> bytes:
        if value is None:
            return b"\xff" * 4
        if isinstance(value, bool):
            value = "true" if value else "false"
        encoded = str(value).encode("utf-8")
        return struct.pack(">I", len(encoded)) + encoded

    fields = (
        "source_row_id",
        "actor_kind",
        "user_id",
        "system_attribution",
        "window_start",
        "model",
        "flow",
        "provider",
        "incognito",
        "input_tokens",
        "output_tokens",
        "cache_read_tokens",
        "cache_creation_tokens",
        "cost_cents",
    )
    preimage = b"orgmesh.usage.batch.v1\0" + field(0) + field(2)
    preimage += b"".join(field(row[name]) for row in batch["rows"] for name in fields)
    assert preimage.hex() == fixture["batch_preimage_hex"]
    assert (
        hashlib.sha256(preimage).hexdigest()
        == "4033481101752459c8ae6026a8f848fba74ae4bdff4a345460074f47de2d3b39"
    )
    encoded = json.dumps(batch, ensure_ascii=False, separators=(",", ":"))
    for char in ("<", ">", "&", "\u2028", "\u2029"):
        encoded = encoded.replace(char, f"\\u{ord(char):04x}")
    assert len(encoded.encode()) == fixture["ack"]["byte_count"] == 742
    manifest_values = (
        7,
        "2026-10-13T00:00:00Z",
        "2026-10-14T00:00:00Z",
        True,
        2,
        742,
        1,
        0,
        batch["digest"],
        2,
        742,
    )
    preimage = b"orgmesh.usage.manifest.v1\0" + b"".join(map(field, manifest_values))
    assert preimage.hex() == fixture["manifest_preimage_hex"]
    assert (
        hashlib.sha256(preimage).hexdigest()
        == "4481da090ed44fa49b3135c7aedeed1da293427ccb8bf0f4753939814987ba55"
    )
    response = {"operation": "usage.begin", "lease": fixture["lease"]}
    result = decode_response(json.dumps(response).encode())
    assert (
        result.lease.coverage.model_dump(mode="json")["from"] == "2026-10-13T00:00:00Z"
    )
    schema = json.loads((root / "v1.schema.json").read_text())
    jsonschema.Draft202012Validator(
        schema, format_checker=jsonschema.FormatChecker()
    ).validate(response)


@pytest.mark.parametrize(
    "changes",
    [
        {"input_tokens": True},
        {"input_tokens": 1.0},
        {"input_tokens": -1},
        {"source_row_id": 2**63},
        {"cost_cents": 0.1},
        {"cost_cents": "0.1"},
        {"cost_cents": "1000000000000.000000"},
        {"cost_cents": "0.0000001"},
        {"actor_kind": "SYSTEM"},
        {"system_attribution": "ATTRIBUTED"},
        {"provider": "a\x00b"},
        {"window_start": "2026-10-13T01:00:00Z"},
    ],
)
def test_snapshot_rows_reject_lossy_or_misclassified_values(
    changes: dict[str, object],
) -> None:
    from onyx.orgmesh_enterprise.models import SnapshotRow

    row = {
        "source_row_id": 1,
        "actor_kind": "USER",
        "user_id": None,
        "system_attribution": None,
        "window_start": "2026-10-13T00:00:00Z",
        "model": "模型",
        "flow": "chat",
        "provider": "",
        "incognito": False,
        "input_tokens": 10,
        "output_tokens": 5,
        "cache_read_tokens": 4,
        "cache_creation_tokens": 2,
        "cost_cents": "0.123456",
    }
    row.update(changes)
    with pytest.raises(ValueError):
        SnapshotRow.model_validate_json(json.dumps(row))


def test_usage_bff_defaults_to_thirty_utc_dates(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from types import SimpleNamespace

    from onyx.db.models import User
    from onyx.orgmesh_enterprise.config import EnterpriseConfig
    from onyx.orgmesh_enterprise.models import UsageSummaryRequest, UsageSummaryResponse
    from onyx.server.features.orgmesh_enterprise import api

    received: list[UsageQuery] = []

    def call(
        _operation: object, _identity: object, request: UsageSummaryRequest
    ) -> UsageSummaryResponse:
        received.append(request.query)
        return UsageSummaryResponse.model_validate_json(
            json.dumps(
                {
                    "operation": "usage.summary",
                    "summary": {
                        "status": "unavailable",
                        "activated_at": None,
                        "collection_start": None,
                        "coverage": None,
                        "published_at": None,
                        "revision": 0,
                        "groups": [],
                        "group_by": "day",
                        "cost_basis": "source_estimate_usd_cents",
                        "cost_notice": "Source-estimated USD cents; 0 may mean missing pricing. Not settled charges.",
                    },
                }
            )
        )

    monkeypatch.setattr(api, "get_config", lambda: EnterpriseConfig(usage_enabled=True))
    monkeypatch.setattr(api, "get_client", lambda: SimpleNamespace(call=call))
    monkeypatch.setattr(api, "authorize_enterprise_operation", lambda *_args: None)
    api.usage_summary_route(user=User())
    day = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    assert received[0].group_by == "day"
    assert received[0].start == day - timedelta(days=29)
    assert received[0].end == day + timedelta(days=1)


def test_summary_dimension_is_allowlisted() -> None:
    day = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    for dimension in ("day", "model", "flow"):
        query = UsageQuery(start=day, end=day + timedelta(days=1), group_by=dimension)
        assert query.group_by == dimension
    with pytest.raises(ValueError):
        UsageQuery(start=day, end=day + timedelta(days=1), group_by="user_id")


def test_shared_summary_has_separate_actor_money_without_grand_total() -> None:
    from pathlib import Path

    import jsonschema

    root = Path(__file__).resolve().parents[4] / "contracts/orgmesh-enterprise"
    payload = json.loads((root / "fixtures/usage-summary.json").read_text())
    response = decode_response(json.dumps(payload).encode())
    assert response.summary.group_by == "day"
    assert len(response.summary.groups) == 4
    assert all(
        group.totals.cost_cents == "0.123456" for group in response.summary.groups
    )
    schema = json.loads((root / "v1.schema.json").read_text())
    jsonschema.Draft202012Validator(
        schema, format_checker=jsonschema.FormatChecker()
    ).validate(payload)
    payload["summary"]["totals"] = {}
    with pytest.raises(ValueError):
        decode_response(json.dumps(payload).encode())
