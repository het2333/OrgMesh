# SPDX-License-Identifier: MIT
"""Read the Community daily rollup in a fresh, immutable source transaction."""

import time
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import Numeric, cast, func, select

from onyx.db.engine.orgmesh_snapshot import remaining_seconds
from onyx.db.engine.sql_engine import get_session_with_tenant
from onyx.db.models import UserUsage
from onyx.orgmesh_enterprise.config import EnterpriseConfig
from onyx.orgmesh_enterprise.models import Coverage, SnapshotRow

MAX_SNAPSHOT_ROWS = 100000
SOURCE_DEADLINE_SECONDS = 45


@dataclass(frozen=True)
class UsageSnapshot:
    coverage: Coverage
    rows: tuple[SnapshotRow, ...]


def _exact_cost(value: object) -> str:
    if not isinstance(value, Decimal):
        raise ValueError("source cost must be an exact six-place Decimal")
    exponent = value.as_tuple().exponent
    if (
        not value.is_finite()
        or not isinstance(exponent, int)
        or exponent < -6
        or value < 0
        or value > Decimal("999999999999.999999")
    ):
        raise ValueError("source cost must be an exact six-place Decimal")
    return format(value, ".6f")


def _utc_source_time(value: datetime) -> datetime:
    if value.utcoffset() is None:
        raise ValueError("source window requires a timezone")
    return value.astimezone(timezone.utc)


def read_usage_snapshot(
    *, tenant_id: str, start: datetime, end: datetime, deadline: float | None = None
) -> UsageSnapshot:
    config = EnterpriseConfig.from_env()
    if not config.usage_enabled or not tenant_id or tenant_id != config.tenant_id:
        raise ValueError("usage source collection requires the configured organization")
    coverage = Coverage.model_validate({"from": start, "to": end})
    deadline = (
        deadline if deadline is not None else time.monotonic() + SOURCE_DEADLINE_SECONDS
    )
    remaining_seconds(deadline)
    statement = (
        select(
            UserUsage.id,
            UserUsage.actor_kind,
            UserUsage.user_id,
            UserUsage.system_attribution,
            UserUsage.window_start,
            UserUsage.model,
            UserUsage.flow,
            UserUsage.provider,
            UserUsage.incognito,
            UserUsage.input_tokens,
            UserUsage.output_tokens,
            UserUsage.cache_read_tokens,
            UserUsage.cache_creation_tokens,
            cast(UserUsage.cost_cents, Numeric(18, 6, asdecimal=True)).label(
                "cost_cents"
            ),
        )
        .where(UserUsage.window_start >= start, UserUsage.window_start < end)
        .order_by(UserUsage.id)
        .limit(MAX_SNAPSHOT_ROWS + 1)
        .execution_options(yield_per=1000)
    )
    rows: list[SnapshotRow] = []
    with get_session_with_tenant(
        tenant_id=tenant_id, snapshot_deadline=deadline
    ) as session:
        session.connection(
            execution_options={
                "isolation_level": "REPEATABLE READ",
                "postgresql_readonly": True,
            }
        )
        milliseconds = max(1, int(remaining_seconds(deadline) * 1000))
        for setting, duration in (
            ("statement_timeout", milliseconds),
            ("lock_timeout", min(milliseconds, 2000)),
            ("idle_in_transaction_session_timeout", milliseconds),
        ):
            remaining_seconds(deadline)
            session.execute(select(func.set_config(setting, str(duration), True)))
        for source in session.execute(statement).mappings():
            remaining_seconds(deadline)
            if len(rows) >= MAX_SNAPSHOT_ROWS:
                raise ValueError("usage source exceeds complete snapshot limit")
            rows.append(
                SnapshotRow(
                    source_row_id=source["id"],
                    actor_kind=source["actor_kind"].value,
                    user_id=str(source["user_id"])
                    if source["user_id"] is not None
                    else None,
                    system_attribution=source["system_attribution"].value
                    if source["system_attribution"] is not None
                    else None,
                    window_start=_utc_source_time(source["window_start"]),
                    model=source["model"],
                    flow=source["flow"],
                    provider=source["provider"],
                    incognito=source["incognito"],
                    input_tokens=source["input_tokens"],
                    output_tokens=source["output_tokens"],
                    cache_read_tokens=source["cache_read_tokens"],
                    cache_creation_tokens=source["cache_creation_tokens"],
                    cost_cents=_exact_cost(source["cost_cents"]),
                )
            )
    remaining_seconds(deadline)
    return UsageSnapshot(coverage=coverage, rows=tuple(rows))
