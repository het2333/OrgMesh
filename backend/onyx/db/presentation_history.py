"""Add owner-scoped history without moving Presenton slides or files."""

import hashlib
from datetime import datetime, timezone
from uuid import UUID, uuid4

from pydantic import JsonValue
from sqlalchemy import case, func, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from onyx.db.chat import get_chat_session_by_id
from onyx.db.models import PresentationRecord, PresentationTask
from onyx.db.projects import check_project_ownership
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
from onyx.presentation_history.contract import HistoryFact, project_history_python

TERMINAL_STATUSES = ("completed", "error")
ENGINE_STATUSES = ("pending", *TERMINAL_STATUSES)


def validate_source(
    db_session: Session,
    owner: UUID,
    project_id: int | None,
    source_chat_id: UUID | None,
) -> tuple[int | None, UUID | None]:
    if source_chat_id is not None:
        try:
            source = get_chat_session_by_id(source_chat_id, owner, db_session)
        except ValueError as exc:
            raise OnyxError(
                OnyxErrorCode.NOT_FOUND, "Source conversation is unavailable"
            ) from exc
        if source.user_id != owner or source.deleted:
            raise OnyxError(
                OnyxErrorCode.NOT_FOUND, "Source conversation is unavailable"
            )
        if source.incognito_record_mode is not None:
            raise OnyxError(
                OnyxErrorCode.INVALID_INPUT,
                "Private conversations cannot be linked to presentation history",
            )
        if (
            project_id is not None
            and source.project_id is not None
            and source.project_id != project_id
        ):
            raise OnyxError(
                OnyxErrorCode.INVALID_INPUT,
                "Source conversation belongs to another project",
            )
        if project_id is None:
            project_id = source.project_id
    if project_id is not None and not check_project_ownership(
        project_id, owner, db_session
    ):
        raise OnyxError(OnyxErrorCode.NOT_FOUND, "Project is unavailable")
    return project_id, source_chat_id


def visible_source(
    db_session: Session, owner: UUID, task: PresentationTask
) -> tuple[int | None, UUID | None]:
    try:
        return validate_source(db_session, owner, task.project_id, task.source_chat_id)
    except (OnyxError, ValueError):
        # Recheck access at read time. Do not expose deleted or revoked links.
        return None, None


def reserve_generation(
    db_session: Session,
    owner: UUID,
    project_id: int | None,
    source_chat_id: UUID | None,
) -> PresentationTask:
    now = datetime.now(timezone.utc)
    task = PresentationTask(
        id=uuid4(),
        user_id=owner,
        project_id=project_id,
        source_chat_id=source_chat_id,
        status="submitting",
        created_at=now,
        updated_at=now,
    )
    db_session.add(task)
    db_session.commit()
    return task


def _lock_engine_task(db_session: Session, owner: UUID, engine_task_id: UUID) -> None:
    if db_session.get_bind().dialect.name == "postgresql":
        # All bridge writers use the same lock before syncing or binding this ID.
        digest = hashlib.sha256(owner.bytes + engine_task_id.bytes).digest()
        key = int.from_bytes(digest[:8], "big", signed=True)
        db_session.execute(select(func.pg_advisory_xact_lock(key)))


def link_generation(
    db_session: Session, owner: UUID, task_id: UUID, engine_task_id: UUID
) -> None:
    _lock_engine_task(db_session, owner, engine_task_id)
    reserved = db_session.scalars(
        select(PresentationTask)
        .where(PresentationTask.id == task_id, PresentationTask.user_id == owner)
        .with_for_update()
    ).first()
    if reserved is None:
        raise OnyxError(OnyxErrorCode.NOT_FOUND, "Presentation attempt is unavailable")
    if reserved.engine_task_id == engine_task_id:
        db_session.commit()
        return
    if reserved.engine_task_id is not None or reserved.status != "submitting":
        raise OnyxError(
            OnyxErrorCode.INVALID_INPUT, "Presentation attempt is already resolved"
        )
    imported = db_session.scalars(
        select(PresentationTask)
        .where(
            PresentationTask.user_id == owner,
            PresentationTask.engine_task_id == engine_task_id,
        )
        .with_for_update()
    ).first()
    if imported is not None:
        if not imported.is_imported:
            raise OnyxError(
                OnyxErrorCode.BAD_GATEWAY,
                "Engine task is already linked to another attempt",
            )
        # A concurrent poll may observe a completed job before POST binds its ID.
        status, deck = imported.status, imported.presentation_id
        db_session.execute(
            update(PresentationRecord)
            .where(
                PresentationRecord.user_id == owner,
                PresentationRecord.task_id == imported.id,
            )
            .values(task_id=reserved.id)
        )
        db_session.delete(imported)
        db_session.flush()
        reserved.status, reserved.presentation_id = status, deck
    else:
        reserved.status = "pending"
    reserved.engine_task_id = engine_task_id
    reserved.updated_at = datetime.now(timezone.utc)
    db_session.commit()


def fail_generation(db_session: Session, owner: UUID, task_id: UUID) -> None:
    db_session.execute(
        update(PresentationTask)
        .where(
            PresentationTask.id == task_id,
            PresentationTask.user_id == owner,
            PresentationTask.status == "submitting",
        )
        .values(status="error", updated_at=datetime.now(timezone.utc))
    )
    db_session.commit()


def _engine_uuid(value: JsonValue) -> UUID:
    if isinstance(value, str):
        try:
            return UUID(value)
        except ValueError:
            pass
    raise OnyxError(OnyxErrorCode.BAD_GATEWAY, "Invalid presentation history response")


def _created_at(value: JsonValue, fallback: datetime) -> datetime:
    if isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value)
            return (
                parsed.replace(tzinfo=timezone.utc) if parsed.tzinfo is None else parsed
            )
        except ValueError:
            pass
    return fallback


def _records(value: JsonValue) -> list[dict[str, JsonValue]]:
    if not isinstance(value, list) or any(not isinstance(item, dict) for item in value):
        raise OnyxError(
            OnyxErrorCode.BAD_GATEWAY, "Invalid presentation history response"
        )
    return [item for item in value if isinstance(item, dict)]


def _upsert_presentation(
    db_session: Session,
    owner: UUID,
    engine_id: UUID,
    task_id: UUID | None,
    title: str | None,
    created_at: datetime,
) -> PresentationRecord:
    now = datetime.now(timezone.utc)
    stmt = insert(PresentationRecord).values(
        id=uuid4(),
        user_id=owner,
        engine_presentation_id=engine_id,
        task_id=task_id,
        title=title,
        created_at=created_at,
        updated_at=now,
    )
    stmt = stmt.on_conflict_do_update(
        index_elements=[
            PresentationRecord.user_id,
            PresentationRecord.engine_presentation_id,
        ],
        set_={
            "task_id": func.coalesce(PresentationRecord.task_id, stmt.excluded.task_id),
            "title": func.coalesce(stmt.excluded.title, PresentationRecord.title),
            "updated_at": now,
        },
    )
    return db_session.scalars(
        stmt.returning(PresentationRecord),
        execution_options={"populate_existing": True},
    ).one()


def _task_metadata(
    db_session: Session, owner: UUID, task: PresentationTask
) -> dict[str, JsonValue]:
    project, source = visible_source(db_session, owner, task)
    return {
        "platform_task_id": str(task.id),
        "source_chat_id": str(source) if source else None,
        "project_id": project,
    }


def sync_jobs(
    db_session: Session, owner: UUID, value: JsonValue
) -> list[dict[str, JsonValue]]:
    rows = _records(value)
    # Validate the complete batch before any write.
    parsed: list[tuple[dict[str, JsonValue], UUID, str, UUID | None]] = []
    for row in rows:
        status = row.get("status")
        if not isinstance(status, str) or status not in ENGINE_STATUSES:
            raise OnyxError(
                OnyxErrorCode.BAD_GATEWAY, "Unknown presentation task status"
            )
        data = row.get("data")
        deck = data.get("presentation_id") if isinstance(data, dict) else None
        parsed.append(
            (
                row,
                _engine_uuid(row.get("id")),
                status,
                _engine_uuid(deck) if deck is not None else None,
            )
        )
    result: list[dict[str, JsonValue]] = []
    now = datetime.now(timezone.utc)
    # Stable lock order prevents batch polls from deadlocking each other.
    for engine_id in sorted({item[1] for item in parsed}):
        _lock_engine_task(db_session, owner, engine_id)
    for row, engine_id, status, deck in parsed:
        stmt = insert(PresentationTask).values(
            id=uuid4(),
            user_id=owner,
            engine_task_id=engine_id,
            presentation_id=deck,
            status=status,
            is_imported=True,
            created_at=_created_at(row.get("created_at"), now),
            updated_at=now,
        )
        stmt = stmt.on_conflict_do_update(
            index_elements=[PresentationTask.user_id, PresentationTask.engine_task_id],
            set_={
                "status": case(
                    (
                        PresentationTask.status.in_(TERMINAL_STATUSES),
                        PresentationTask.status,
                    ),
                    else_=stmt.excluded.status,
                ),
                "presentation_id": func.coalesce(
                    PresentationTask.presentation_id, stmt.excluded.presentation_id
                ),
                "updated_at": now,
            },
        )
        task = db_session.scalars(
            stmt.returning(PresentationTask),
            execution_options={"populate_existing": True},
        ).one()
        if task.presentation_id is not None:
            _upsert_presentation(
                db_session, owner, task.presentation_id, task.id, None, task.created_at
            )
        data = row.get("data")
        persisted_data: JsonValue = data
        if task.presentation_id is not None:
            persisted_data = {
                **(data if isinstance(data, dict) else {}),
                "presentation_id": str(task.presentation_id),
            }
        result.append(
            {
                **row,
                "status": task.status,
                "data": persisted_data,
                **_task_metadata(db_session, owner, task),
            }
        )
    db_session.commit()
    return result


def sync_presentations(
    db_session: Session, owner: UUID, value: JsonValue
) -> list[dict[str, JsonValue]]:
    rows = _records(value)
    parsed = [(row, _engine_uuid(row.get("id"))) for row in rows]
    result: list[dict[str, JsonValue]] = []
    now = datetime.now(timezone.utc)
    for row, engine_id in parsed:
        task = db_session.scalars(
            select(PresentationTask)
            .where(
                PresentationTask.user_id == owner,
                PresentationTask.presentation_id == engine_id,
            )
            .order_by(PresentationTask.created_at, PresentationTask.id)
            .limit(1)
        ).first()
        title = row.get("title")
        record = _upsert_presentation(
            db_session,
            owner,
            engine_id,
            task.id if task else None,
            title if isinstance(title, str) else None,
            _created_at(row.get("created_at"), now),
        )
        # A previous import may already have linked the original generation task.
        if record.task_id is not None:
            task = db_session.scalars(
                select(PresentationTask).where(
                    PresentationTask.id == record.task_id,
                    PresentationTask.user_id == owner,
                )
            ).first()
        metadata = (
            _task_metadata(db_session, owner, task)
            if task
            else {"platform_task_id": None, "source_chat_id": None, "project_id": None}
        )
        result.append({**row, "platform_presentation_id": str(record.id), **metadata})
    db_session.commit()
    return result


def history_facts_for_owner(
    db_session: Session, owner: UUID, limit: int, offset: int, status: str | None = None
) -> list[HistoryFact]:
    query = select(PresentationTask).where(PresentationTask.user_id == owner)
    if status is not None:
        query = query.where(PresentationTask.status == status)
    tasks = db_session.scalars(
        query.order_by(PresentationTask.created_at.desc(), PresentationTask.id.desc())
        .limit(limit)
        .offset(offset)
    ).all()
    facts: list[HistoryFact] = []
    for task in tasks:
        project, source = visible_source(db_session, owner, task)
        facts.append(
            HistoryFact(
                platform_id=task.id,
                engine_task_id=task.engine_task_id,
                deck_id=task.presentation_id,
                state=task.status,
                visible_project_id=project,
                visible_source_chat_id=source,
                created_at=task.created_at.isoformat(),
                updated_at=task.updated_at.isoformat(),
            )
        )
    return facts


def history_for_owner(
    db_session: Session, owner: UUID, limit: int, offset: int, status: str | None = None
) -> list[dict[str, JsonValue]]:
    return project_history_python(
        history_facts_for_owner(db_session, owner, limit, offset, status)
    )
