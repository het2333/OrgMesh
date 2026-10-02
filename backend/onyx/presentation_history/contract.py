"""Immutable values for one authorized history page. No I/O or permissions."""

import json
import unicodedata
from typing import Annotated, Literal, Sequence, TypeVar
from uuid import UUID

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    JsonValue,
    field_validator,
    model_validator,
)

MAX_BYTES = 256 * 1024
MAX_RECORDS = 100
HistoryStatus = Literal["submitting", "pending", "completed", "error"]
TimestampText = Annotated[str, Field(min_length=1, max_length=64)]
ProjectID = Annotated[int, Field(ge=-(2**63), le=2**63 - 1)]


class ImmutableValue(BaseModel):
    model_config = ConfigDict(frozen=True, strict=True, extra="forbid")

    @field_validator("*", mode="before")
    @classmethod
    def bounded_text(cls, value: object) -> object:
        if isinstance(value, str) and any(
            unicodedata.category(c) == "Cc" for c in value
        ):
            raise ValueError("control_character")
        return value


class HistoryQuery(ImmutableValue):
    limit: Annotated[int, Field(ge=1, le=100)]
    offset: Annotated[int, Field(ge=0, le=100000)]
    status: HistoryStatus | None


class HistoryFact(ImmutableValue):
    platform_id: UUID
    engine_task_id: UUID | None
    deck_id: UUID | None
    state: HistoryStatus
    visible_project_id: ProjectID | None
    visible_source_chat_id: UUID | None
    created_at: TimestampText
    updated_at: TimestampText


class HistoryRow(ImmutableValue):
    platform_task_id: str
    task_id: str | None
    presentation_id: str | None
    status: HistoryStatus
    project_id: ProjectID | None
    source_chat_id: str | None
    created_at: TimestampText
    updated_at: TimestampText

    @field_validator("platform_task_id", "task_id", "presentation_id", "source_chat_id")
    @classmethod
    def canonical_uuid(cls, value: str | None) -> str | None:
        if value is not None and str(UUID(value)) != value:
            raise ValueError("invalid_uuid")
        return value


class VersionedValue(ImmutableValue):
    version: Literal[1]
    request_id: UUID

    @field_validator("version", mode="before")
    @classmethod
    def exact_version(cls, value: object) -> object:
        if type(value) is not int or value != 1:
            raise ValueError("unsupported_version")
        return value


class HistoryProjectionRequest(VersionedValue):
    query: HistoryQuery
    facts: Annotated[
        tuple[HistoryFact, ...], Field(max_length=MAX_RECORDS, strict=False)
    ]

    @model_validator(mode="after")
    def authorized_page(self) -> "HistoryProjectionRequest":
        if len(self.facts) > self.query.limit:
            raise ValueError("page_bound")
        if len({f.platform_id for f in self.facts}) != len(self.facts):
            raise ValueError("duplicate_platform_id")
        if self.query.status is not None and any(
            f.state != self.query.status for f in self.facts
        ):
            raise ValueError("status_mismatch")
        return self


class HistoryProjectionResponse(VersionedValue):
    rows: Annotated[tuple[HistoryRow, ...], Field(max_length=MAX_RECORDS, strict=False)]

    @model_validator(mode="after")
    def unique_rows(self) -> "HistoryProjectionResponse":
        if len({r.platform_task_id for r in self.rows}) != len(self.rows):
            raise ValueError("duplicate_platform_id")
        return self

    def rows_json(self) -> list[dict[str, JsonValue]]:
        return [row.model_dump(mode="json") for row in self.rows]


Value = TypeVar("Value", bound=ImmutableValue)


def _unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate_key")
        result[key] = value
    return result


def _invalid_constant(_value: str) -> None:
    raise ValueError("invalid_number")


def _decode(data: bytes, model: type[Value]) -> Value:
    if len(data) > MAX_BYTES:
        raise ValueError("body_bound")
    try:
        json.loads(
            data,
            object_pairs_hook=_unique_object,
            parse_constant=_invalid_constant,
        )
        return model.model_validate_json(data)
    except (UnicodeError, RecursionError, json.JSONDecodeError) as exc:
        raise ValueError("invalid_json") from exc


def decode_request(data: bytes) -> HistoryProjectionRequest:
    return _decode(data, HistoryProjectionRequest)


def decode_response(data: bytes) -> HistoryProjectionResponse:
    return _decode(data, HistoryProjectionResponse)


def project_history_python(facts: Sequence[HistoryFact]) -> list[dict[str, JsonValue]]:
    return [
        {
            "platform_task_id": str(f.platform_id),
            "task_id": str(f.engine_task_id) if f.engine_task_id is not None else None,
            "presentation_id": str(f.deck_id) if f.deck_id is not None else None,
            "status": f.state,
            "project_id": f.visible_project_id,
            "source_chat_id": str(f.visible_source_chat_id)
            if f.visible_source_chat_id is not None
            else None,
            "created_at": f.created_at,
            "updated_at": f.updated_at,
        }
        for f in facts
    ]
