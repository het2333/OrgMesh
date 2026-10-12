# SPDX-License-Identifier: MIT
"""Bounded, immutable values for the version-one private service contract."""

import json
import unicodedata
from datetime import datetime, timedelta, timezone
from enum import StrEnum
from typing import Annotated, Literal
from uuid import UUID

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    TypeAdapter,
    field_validator,
    model_validator,
)

MAX_BYTES = 1024 * 1024
LOGO_ASSET_IDS = frozenset({"orgmesh-default"})
AUDIENCE = "orgmesh-enterprise/v1"


class EnterpriseOperation(StrEnum):
    BRANDING_READ = "branding.read"
    BRANDING_PATCH = "branding.patch"
    AUDIT_LIST = "audit.list"
    USAGE_SUMMARY = "usage.summary"
    USAGE_BEGIN = "usage.begin"
    USAGE_STAGE = "usage.stage"
    USAGE_COMMIT = "usage.commit"


class ContractModel(BaseModel):
    model_config = ConfigDict(
        frozen=True, strict=True, extra="forbid", allow_inf_nan=False
    )


class TrustedIdentity(ContractModel):
    version: Literal[1] = 1
    tenant_id: Annotated[str, Field(min_length=1, max_length=128)]
    actor_kind: Literal["anonymous", "user", "producer"]
    user_id: UUID | Literal[""]
    operation: EnterpriseOperation
    request_id: UUID
    audience: Literal["orgmesh-enterprise/v1"] = AUDIENCE
    issued_at: datetime
    expires_at: datetime

    @field_validator("version", mode="before")
    @classmethod
    def exact_version(cls, value: object) -> object:
        if type(value) is not int or value != 1:
            raise ValueError("unsupported identity version")
        return value

    @model_validator(mode="after")
    def valid_context(self) -> "TrustedIdentity":
        if self.issued_at.tzinfo is None or self.expires_at.tzinfo is None:
            raise ValueError("context requires timezone-aware timestamps")
        lifetime = (self.expires_at - self.issued_at).total_seconds()
        if not 0 < lifetime <= 5:
            raise ValueError("invalid context lifetime")
        producer_operations = {
            EnterpriseOperation.USAGE_BEGIN,
            EnterpriseOperation.USAGE_STAGE,
            EnterpriseOperation.USAGE_COMMIT,
        }
        if self.actor_kind == "producer":
            if self.user_id != "" or self.operation not in producer_operations:
                raise ValueError("producer context requires a snapshot operation")
        elif self.operation in producer_operations:
            raise ValueError("snapshot operation requires producer context")
        if self.actor_kind == "anonymous":
            if (
                self.operation != EnterpriseOperation.BRANDING_READ
                or self.user_id != ""
            ):
                raise ValueError("anonymous context only permits branding.read")
        elif self.actor_kind == "user" and not isinstance(self.user_id, UUID):
            raise ValueError("user context requires a user ID")
        return self


class EnterpriseContext(ContractModel):
    user_id: UUID
    tenant_id: Annotated[str, Field(min_length=1, max_length=128)]


class BrandingFields(ContractModel):
    name: Annotated[str, Field(min_length=1, max_length=50)]
    greeting: Annotated[str, Field(max_length=120)]
    logo_asset_id: Literal["orgmesh-default"]

    @field_validator("name", "greeting")
    @classmethod
    def plain_text(cls, value: str) -> str:
        if (
            "<" in value
            or ">" in value
            or any(unicodedata.category(c) == "Cc" and c not in "\n\t" for c in value)
        ):
            raise ValueError("branding must be plain text")
        return value

    @field_validator("logo_asset_id")
    @classmethod
    def reviewed_logo(cls, value: str) -> str:
        if value not in LOGO_ASSET_IDS:
            raise ValueError("logo asset is not reviewed")
        return value


class BrandingPatch(BrandingFields):
    expected_version: Annotated[int, Field(ge=0, le=2**63 - 1)]


class BrandingView(BrandingFields):
    version: Annotated[int, Field(ge=0, le=2**63 - 1)]
    source: Literal["static", "dynamic"]

    @model_validator(mode="after")
    def persistent_version(self) -> "BrandingView":
        if (self.source == "static" and self.version != 0) or (
            self.source == "dynamic" and self.version == 0
        ):
            raise ValueError("branding source and persisted version differ")
        return self


class AuditQuery(ContractModel):
    start: datetime
    end: datetime
    limit: Annotated[int, Field(ge=1, le=100)] = 50
    cursor: Annotated[str, Field(max_length=512)] = ""
    action: Literal["", "branding.created", "branding.updated"] = ""
    result: Literal["", "success"] = ""

    @model_validator(mode="after")
    def valid_range(self) -> "AuditQuery":
        if (
            self.start.tzinfo is None
            or self.end.tzinfo is None
            or not timedelta(0) < self.end - self.start <= timedelta(days=90)
        ):
            raise ValueError("audit range must be within 90 days")
        return self


class AuditEvent(ContractModel):
    event_id: UUID
    created_at: datetime
    user_id: UUID
    actor_kind: Literal["user"]
    resource_id: Literal["branding-config"]
    action: Literal["branding.created", "branding.updated"]
    result: Literal["success"]
    before_version: Annotated[int, Field(ge=0, le=2**63 - 1)]
    after_version: Annotated[int, Field(ge=1, le=2**63 - 1)]
    changed_fields: tuple[Literal["name", "greeting", "logo_asset_id"], ...]
    request_id: UUID

    @model_validator(mode="after")
    def valid_change(self) -> "AuditEvent":
        if (
            self.created_at.tzinfo is None
            or self.after_version - 1 != self.before_version
            or (self.action == "branding.created" and self.before_version != 0)
            or (self.action == "branding.updated" and self.before_version == 0)
            or not 1 <= len(self.changed_fields) <= 3
            or len(set(self.changed_fields)) != len(self.changed_fields)
        ):
            raise ValueError("invalid branding audit change")
        return self


class AuditPage(ContractModel):
    events: Annotated[tuple[AuditEvent, ...], Field(max_length=100)]
    next_cursor: Annotated[str, Field(max_length=512)] | None


class UsageQuery(ContractModel):
    group_by: Literal["day", "model", "flow"] = "day"
    start: datetime
    end: datetime

    @model_validator(mode="after")
    def valid_range(self) -> "UsageQuery":
        today = datetime.now(timezone.utc).replace(
            hour=0, minute=0, second=0, microsecond=0
        )
        if (
            not _utc_midnight(self.start)
            or not _utc_midnight(self.end)
            or self.start >= self.end
            or self.start < today - timedelta(days=89)
            or self.end > today + timedelta(days=1)
        ):
            raise ValueError("usage range must select the most recent 90 UTC dates")
        return self


def _utc_midnight(value: datetime) -> bool:
    return value.utcoffset() == timedelta(0) and value.time().isoformat() == "00:00:00"


class Coverage(ContractModel):
    model_config = ConfigDict(serialize_by_alias=True)
    from_: datetime = Field(alias="from")
    to: datetime

    @model_validator(mode="after")
    def valid_days(self) -> "Coverage":
        if (
            not _utc_midnight(self.from_)
            or not _utc_midnight(self.to)
            or not timedelta(0) < self.to - self.from_ <= timedelta(days=90)
        ):
            raise ValueError("coverage requires whole UTC daily buckets")
        return self


TokenCount = Annotated[int, Field(ge=0, le=2**63 - 1)]
TokenTotal = Annotated[str, Field(pattern=r"^(0|[1-9][0-9]{0,31})$")]
CostCents = Annotated[str, Field(pattern=r"^(0|[1-9][0-9]{0,11})\.[0-9]{6}$")]
CostTotal = Annotated[str, Field(pattern=r"^(0|[1-9][0-9]{0,31})\.[0-9]{6}$")]
Digest = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]


class SnapshotRow(ContractModel):
    source_row_id: Annotated[int, Field(ge=1, le=2**63 - 1)]
    actor_kind: Literal["USER", "SYSTEM"]
    user_id: (
        Annotated[
            str,
            Field(
                pattern=r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"
            ),
        ]
        | None
    )
    system_attribution: Literal["ATTRIBUTED", "UNATTRIBUTED"] | None
    window_start: datetime
    model: Annotated[str, Field(min_length=1, max_length=512)]
    flow: Annotated[str, Field(min_length=1, max_length=512)]
    provider: Annotated[str, Field(max_length=512)]
    incognito: bool
    input_tokens: TokenCount
    output_tokens: TokenCount
    cache_read_tokens: TokenCount
    cache_creation_tokens: TokenCount
    cost_cents: CostCents

    @field_validator("model", "flow", "provider")
    @classmethod
    def valid_source_text(cls, value: str) -> str:
        if "\x00" in value:
            raise ValueError("source text contains NUL")
        value.encode("utf-8", errors="strict")
        return value

    @model_validator(mode="after")
    def source_classification(self) -> "SnapshotRow":
        if not _utc_midnight(self.window_start):
            raise ValueError("source row requires UTC midnight")
        if self.actor_kind == "USER":
            if self.system_attribution is not None:
                raise ValueError("user attribution must be null")
        elif (
            self.user_id is not None
            or self.incognito
            or self.system_attribution is None
        ):
            raise ValueError("invalid system attribution")
        return self


class SnapshotLease(ContractModel):
    status: Literal["waiting", "ready"]
    revision: Annotated[int, Field(ge=0, le=2**63 - 1)]
    activated_at: datetime
    collection_start: datetime
    coverage: Coverage | None
    expires_at: datetime | None

    @model_validator(mode="after")
    def valid_lease(self) -> "SnapshotLease":
        if self.activated_at.tzinfo is None or not _utc_midnight(self.collection_start):
            raise ValueError("activation requires UTC boundary")
        expected = self.activated_at.astimezone(timezone.utc).replace(
            hour=0, minute=0, second=0, microsecond=0
        ) + timedelta(days=1)
        if self.collection_start != expected:
            raise ValueError("collection must start the following UTC day")
        if self.status == "waiting":
            if (
                self.revision != 0
                or self.coverage is not None
                or self.expires_at is not None
            ):
                raise ValueError("waiting result has no active lease")
        elif (
            self.revision < 1
            or self.coverage is None
            or self.expires_at is None
            or self.expires_at.tzinfo is None
            or self.coverage.from_ < self.collection_start
        ):
            raise ValueError("ready result requires a fenced lease")
        return self


class SnapshotBatch(ContractModel):
    index: Annotated[int, Field(ge=0, lt=100000)]
    rows: Annotated[tuple[SnapshotRow, ...], Field(min_length=1, max_length=1000)]
    digest: Digest


class StageAck(ContractModel):
    index: Annotated[int, Field(ge=0, lt=100000)]
    digest: Digest
    row_count: Annotated[int, Field(ge=1, le=1000)]
    byte_count: Annotated[int, Field(ge=1, le=MAX_BYTES)]


class SnapshotManifest(ContractModel):
    complete: bool
    batches: Annotated[tuple[StageAck, ...], Field(max_length=100000)]
    total_rows: Annotated[int, Field(ge=0, le=100000)]
    total_bytes: Annotated[int, Field(ge=0, le=64 * MAX_BYTES)]
    digest: Digest

    @model_validator(mode="after")
    def complete_manifest(self) -> "SnapshotManifest":
        if (
            not self.complete
            or any(batch.index != index for index, batch in enumerate(self.batches))
            or sum(batch.row_count for batch in self.batches) != self.total_rows
            or sum(batch.byte_count for batch in self.batches) != self.total_bytes
        ):
            raise ValueError("manifest must describe a complete ordered snapshot")
        return self


class PublishedSnapshot(ContractModel):
    revision: Annotated[int, Field(ge=1, le=2**63 - 1)]
    digest: Digest
    coverage: Coverage
    published_at: datetime
    total_rows: Annotated[int, Field(ge=0, le=100000)]
    total_bytes: Annotated[int, Field(ge=0, le=64 * MAX_BYTES)]

    @field_validator("published_at")
    @classmethod
    def aware_publication(cls, value: datetime) -> datetime:
        if value.tzinfo is None:
            raise ValueError("publication requires a timezone")
        return value


class UsageTotals(ContractModel):
    input_tokens: TokenTotal
    output_tokens: TokenTotal
    total_tokens: TokenTotal
    cache_read_tokens: TokenTotal
    cache_creation_tokens: TokenTotal
    cost_cents: CostTotal

    @model_validator(mode="after")
    def total_excludes_cache(self) -> "UsageTotals":
        if int(self.total_tokens) != int(self.input_tokens) + int(self.output_tokens):
            raise ValueError("total tokens must be input plus output")
        return self


class UsageGroup(ContractModel):
    value: Annotated[str, Field(min_length=1, max_length=512)]
    category: Literal["USER", "SYSTEM_ATTRIBUTED", "SYSTEM_UNATTRIBUTED"]
    incognito: bool
    totals: UsageTotals

    @model_validator(mode="after")
    def privacy_category(self) -> "UsageGroup":
        if self.category != "USER" and self.incognito:
            raise ValueError("system rows cannot be incognito")
        return self


class UsageSummary(ContractModel):
    group_by: Literal["day", "model", "flow"]
    status: Literal["ready", "stale", "waiting", "unavailable"]
    activated_at: datetime | None
    collection_start: datetime | None
    coverage: Coverage | None
    published_at: datetime | None
    revision: Annotated[int, Field(ge=0, le=2**63 - 1)]
    groups: Annotated[tuple[UsageGroup, ...], Field(max_length=1000)]
    cost_basis: Literal["source_estimate_usd_cents"]
    cost_notice: Literal[
        "Source-estimated USD cents; 0 may mean missing pricing. Not settled charges."
    ]

    @model_validator(mode="after")
    def actual_coverage(self) -> "UsageSummary":
        if self.status in ("ready", "stale"):
            if (
                self.coverage is None
                or self.published_at is None
                or self.activated_at is None
                or self.collection_start is None
                or self.revision < 1
            ):
                raise ValueError(
                    "available summary requires publication and activation"
                )
        elif self.coverage is not None or self.groups:
            raise ValueError("unavailable summary has no covered totals")
        if len(
            {(group.value, group.category, group.incognito) for group in self.groups}
        ) != len(self.groups):
            raise ValueError("duplicate summary group")
        for value in (self.activated_at, self.collection_start, self.published_at):
            if value is not None and value.tzinfo is None:
                raise ValueError("summary timestamps require a timezone")
        return self


class UsageBeginRequest(ContractModel):
    operation: Literal[EnterpriseOperation.USAGE_BEGIN] = (
        EnterpriseOperation.USAGE_BEGIN
    )
    coverage: Coverage


class UsageStageRequest(ContractModel):
    operation: Literal[EnterpriseOperation.USAGE_STAGE] = (
        EnterpriseOperation.USAGE_STAGE
    )
    lease: SnapshotLease
    batch: SnapshotBatch


class UsageCommitRequest(ContractModel):
    operation: Literal[EnterpriseOperation.USAGE_COMMIT] = (
        EnterpriseOperation.USAGE_COMMIT
    )
    lease: SnapshotLease
    manifest: SnapshotManifest


class UsageBeginResponse(ContractModel):
    operation: Literal[EnterpriseOperation.USAGE_BEGIN]
    lease: SnapshotLease


class UsageStageResponse(ContractModel):
    operation: Literal[EnterpriseOperation.USAGE_STAGE]
    ack: StageAck


class UsageCommitResponse(ContractModel):
    operation: Literal[EnterpriseOperation.USAGE_COMMIT]
    published: PublishedSnapshot


class BrandingReadRequest(ContractModel):
    operation: Literal[EnterpriseOperation.BRANDING_READ] = (
        EnterpriseOperation.BRANDING_READ
    )


class BrandingPatchRequest(ContractModel):
    operation: Literal[EnterpriseOperation.BRANDING_PATCH] = (
        EnterpriseOperation.BRANDING_PATCH
    )
    patch: BrandingPatch


class AuditListRequest(ContractModel):
    operation: Literal[EnterpriseOperation.AUDIT_LIST] = EnterpriseOperation.AUDIT_LIST
    query: AuditQuery


class UsageSummaryRequest(ContractModel):
    operation: Literal[EnterpriseOperation.USAGE_SUMMARY] = (
        EnterpriseOperation.USAGE_SUMMARY
    )
    query: UsageQuery


RequestModel = Annotated[
    BrandingReadRequest
    | BrandingPatchRequest
    | AuditListRequest
    | UsageSummaryRequest
    | UsageBeginRequest
    | UsageStageRequest
    | UsageCommitRequest,
    Field(discriminator="operation"),
]


class BrandingReadResponse(ContractModel):
    operation: Literal[EnterpriseOperation.BRANDING_READ]
    branding: BrandingView


class BrandingPatchResponse(ContractModel):
    operation: Literal[EnterpriseOperation.BRANDING_PATCH]
    branding: BrandingView


class AuditListResponse(ContractModel):
    operation: Literal[EnterpriseOperation.AUDIT_LIST]
    page: AuditPage


class UsageSummaryResponse(ContractModel):
    operation: Literal[EnterpriseOperation.USAGE_SUMMARY]
    summary: UsageSummary


ResponseModel = Annotated[
    BrandingReadResponse
    | BrandingPatchResponse
    | AuditListResponse
    | UsageSummaryResponse
    | UsageBeginResponse
    | UsageStageResponse
    | UsageCommitResponse,
    Field(discriminator="operation"),
]
REQUEST_ADAPTER = TypeAdapter(RequestModel)
RESPONSE_ADAPTER = TypeAdapter(ResponseModel)


def _unique_pairs(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON key")
        result[key] = value
    return result


def _reject_nonfinite(_value: str) -> None:
    raise ValueError("non-finite JSON value")


def validate_json_bytes(data: bytes) -> None:
    if len(data) > MAX_BYTES:
        raise ValueError("JSON exceeds size limit")
    try:
        json.loads(
            data.decode("utf-8"),
            object_pairs_hook=_unique_pairs,
            parse_constant=_reject_nonfinite,
        )
    except (UnicodeError, RecursionError) as error:
        raise ValueError("invalid JSON") from error


def decode_request(data: bytes) -> RequestModel:
    validate_json_bytes(data)
    return REQUEST_ADAPTER.validate_json(data)


def decode_response(data: bytes) -> ResponseModel:
    validate_json_bytes(data)
    return RESPONSE_ADAPTER.validate_json(data)


class EnterpriseRequestEnvelope(ContractModel):
    version: Literal[1]
    identity: TrustedIdentity
    request: RequestModel

    @field_validator("version", mode="before")
    @classmethod
    def exact_version(cls, value: object) -> object:
        if type(value) is not int or value != 1:
            raise ValueError("unsupported envelope version")
        return value
