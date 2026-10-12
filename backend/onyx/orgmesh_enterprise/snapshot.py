# SPDX-License-Identifier: MIT
"""Publish a complete read-only source view under the Go receiver's fenced lease."""

import hashlib
import json
import os
import struct
import time
from collections.abc import Iterator, Sequence
from datetime import datetime, timedelta, timezone

from onyx.db.engine.orgmesh_snapshot import remaining_seconds
from onyx.db.orgmesh_usage_snapshot import UsageSnapshot as UsageSnapshot
from onyx.db.orgmesh_usage_snapshot import read_usage_snapshot
from onyx.orgmesh_enterprise.client import EnterpriseClient
from onyx.orgmesh_enterprise.config import EnterpriseConfig
from onyx.orgmesh_enterprise.models import (
    MAX_BYTES,
    Coverage,
    SnapshotBatch,
    SnapshotLease,
    SnapshotManifest,
    SnapshotRow,
    StageAck,
)
from shared_configs.contextvars import get_current_tenant_id

TOTAL_DEADLINE_SECONDS = 45
TRANSPORT_RESERVE_SECONDS = 2
BATCH_TARGET_BYTES = 768 * 1024
MAX_REVISION_BYTES = 64 * MAX_BYTES
MAX_REVISION_ROWS = 100000


def _utc_time(value: datetime) -> str:
    return (
        value.astimezone(timezone.utc)
        .isoformat(timespec="seconds")
        .replace("+00:00", "Z")
    )


def _field(value: str | None) -> bytes:
    if value is None:
        return b"\xff\xff\xff\xff"
    data = value.encode("utf-8")
    return struct.pack(">I", len(data)) + data


def batch_preimage(index: int, rows: Sequence[SnapshotRow]) -> bytes:
    output = bytearray(b"orgmesh.usage.batch.v1\x00")
    output.extend(_field(str(index)))
    output.extend(_field(str(len(rows))))
    for row in rows:
        for value in (
            str(row.source_row_id),
            row.actor_kind,
            row.user_id,
            row.system_attribution,
            _utc_time(row.window_start),
            row.model,
            row.flow,
            row.provider,
            "true" if row.incognito else "false",
            str(row.input_tokens),
            str(row.output_tokens),
            str(row.cache_read_tokens),
            str(row.cache_creation_tokens),
            row.cost_cents,
        ):
            output.extend(_field(value))
    return bytes(output)


def batch_digest(index: int, rows: Sequence[SnapshotRow]) -> str:
    return hashlib.sha256(batch_preimage(index, rows)).hexdigest()


def _canonical_json(value: object) -> bytes:
    encoded = json.dumps(
        value, ensure_ascii=False, separators=(",", ":"), allow_nan=False
    )
    for character in ("<", ">", "&", "\u2028", "\u2029"):
        encoded = encoded.replace(character, f"\\u{ord(character):04x}")
    return encoded.encode("utf-8")


def canonical_batch_bytes(batch: SnapshotBatch) -> int:
    return len(_canonical_json(batch.model_dump(mode="json")))


def manifest_preimage(lease: SnapshotLease, batches: Sequence[StageAck]) -> bytes:
    if lease.status != "ready" or lease.coverage is None:
        raise ValueError("a ready lease is required for publication")
    output = bytearray(b"orgmesh.usage.manifest.v1\x00")
    for value in (
        str(lease.revision),
        _utc_time(lease.coverage.from_),
        _utc_time(lease.coverage.to),
        "true",
        str(sum(batch.row_count for batch in batches)),
        str(sum(batch.byte_count for batch in batches)),
        str(len(batches)),
    ):
        output.extend(_field(value))
    for batch in batches:
        for value in (
            str(batch.index),
            batch.digest,
            str(batch.row_count),
            str(batch.byte_count),
        ):
            output.extend(_field(value))
    return bytes(output)


def make_manifest(
    lease: SnapshotLease, batches: Sequence[StageAck]
) -> SnapshotManifest:
    return SnapshotManifest(
        complete=True,
        batches=tuple(batches),
        total_rows=sum(batch.row_count for batch in batches),
        total_bytes=sum(batch.byte_count for batch in batches),
        digest=hashlib.sha256(manifest_preimage(lease, batches)).hexdigest(),
    )


def _batches(
    rows: Sequence[SnapshotRow], *, deadline: float
) -> Iterator[SnapshotBatch]:
    index = 0
    current: list[SnapshotRow] = []
    size = len(_canonical_json({"index": index, "rows": [], "digest": "0" * 64}))
    for row in rows:
        remaining_seconds(deadline)
        row_bytes = len(_canonical_json(row.model_dump(mode="json")))
        if current and (
            len(current) == 1000 or size + row_bytes + 1 > BATCH_TARGET_BYTES
        ):
            yield SnapshotBatch(
                index=index, rows=tuple(current), digest=batch_digest(index, current)
            )
            index += 1
            current = []
            size = len(
                _canonical_json({"index": index, "rows": [], "digest": "0" * 64})
            )
        if size + row_bytes > BATCH_TARGET_BYTES:
            raise ValueError("usage source row exceeds batch budget")
        size += row_bytes + (1 if current else 0)
        current.append(row)
    if current:
        yield SnapshotBatch(
            index=index, rows=tuple(current), digest=batch_digest(index, current)
        )


def _check_lease(
    lease: SnapshotLease, deadline: float, *, transport: bool = False
) -> None:
    reserve = TRANSPORT_RESERVE_SECONDS if transport else 0
    remaining_seconds(deadline, reserve=reserve)
    if (
        lease.expires_at is None
        or (lease.expires_at - datetime.now(timezone.utc)).total_seconds() <= reserve
    ):
        raise TimeoutError("usage snapshot lease expired")


def publish_usage_snapshot(*, tenant_id: str, config: EnterpriseConfig) -> None:
    deadline = time.monotonic() + TOTAL_DEADLINE_SECONDS
    if (
        not tenant_id
        or tenant_id != config.tenant_id
        or tenant_id != get_current_tenant_id()
    ):
        raise ValueError(
            "usage collection requires an explicit configured organization"
        )
    if os.environ.get("MULTI_TENANT", "false").lower() == "true":
        raise ValueError("usage collection requires a single organization")
    if not config.usage_enabled:
        return
    today = datetime.now(timezone.utc).replace(
        hour=0, minute=0, second=0, microsecond=0
    )
    requested = Coverage.model_validate(
        {"from": today - timedelta(days=89), "to": today + timedelta(days=1)}
    )
    client = EnterpriseClient(config)
    remaining_seconds(deadline, reserve=TRANSPORT_RESERVE_SECONDS)
    lease = client.begin(requested, deadline=deadline)
    remaining_seconds(deadline)
    if lease.status == "waiting":
        return
    _check_lease(lease, deadline)
    if (
        lease.coverage is None
        or lease.expires_at is None
        or lease.coverage.from_ < requested.from_
        or lease.coverage.to != requested.to
    ):
        raise ValueError(
            "receiver returned coverage outside the requested daily interval"
        )
    deadline = min(
        deadline,
        time.monotonic()
        + (lease.expires_at - datetime.now(timezone.utc)).total_seconds(),
    )
    source = read_usage_snapshot(
        tenant_id=tenant_id,
        start=lease.coverage.from_,
        end=lease.coverage.to,
        deadline=deadline,
    )
    _check_lease(lease, deadline)
    if source.coverage != lease.coverage or len(source.rows) > MAX_REVISION_ROWS:
        raise ValueError("source view differs from complete leased coverage")
    ids: set[int] = set()
    for row in source.rows:
        remaining_seconds(deadline)
        if (
            row.source_row_id in ids
            or not lease.coverage.from_ <= row.window_start < lease.coverage.to
        ):
            raise ValueError("duplicate or out-of-coverage source row")
        ids.add(row.source_row_id)
    acknowledgments: list[StageAck] = []
    total_bytes = 0
    for batch in _batches(source.rows, deadline=deadline):
        _check_lease(lease, deadline, transport=True)
        batch_bytes = canonical_batch_bytes(batch)
        if total_bytes + batch_bytes > MAX_REVISION_BYTES:
            raise ValueError("usage snapshot exceeds complete byte limit")
        ack = client.stage(lease, batch, deadline=deadline)
        _check_lease(lease, deadline)
        if (
            ack.index != batch.index
            or ack.digest != batch.digest
            or ack.row_count != len(batch.rows)
            or ack.byte_count != batch_bytes
        ):
            raise ValueError("receiver acknowledgment differs from the staged batch")
        acknowledgments.append(ack)
        total_bytes += ack.byte_count
    manifest = make_manifest(lease, acknowledgments)
    _check_lease(lease, deadline, transport=True)
    receipt = client.commit(lease, manifest, deadline=deadline)
    remaining_seconds(deadline)
    if (
        receipt.revision != lease.revision
        or receipt.digest != manifest.digest
        or receipt.coverage != lease.coverage
        or receipt.total_rows != manifest.total_rows
        or receipt.total_bytes != manifest.total_bytes
    ):
        raise ValueError(
            "receiver publication receipt differs from the complete snapshot"
        )
