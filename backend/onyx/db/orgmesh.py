from datetime import datetime, timedelta, timezone
from uuid import UUID

from sqlalchemy import func, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from onyx.access.models import ExternalAccess
from onyx.access.source_access import source_acl_checked_at
from onyx.db.models import Document, OrgMeshDirectoryUser, User

ACL_MAX_AGE_SECONDS = 900


def get_source_document_access(
    db_session: Session, document_ids: list[str]
) -> dict[str, ExternalAccess]:
    rows = db_session.scalars(
        select(Document).where(Document.id.in_(document_ids))
    ).all()
    result: dict[str, ExternalAccess] = {}
    now = datetime.now(timezone.utc).timestamp()
    for row in rows:
        if row.external_user_emails is None and row.external_user_group_ids is None:
            if row.id.startswith("feishu:"):
                result[row.id] = ExternalAccess.empty()
            continue
        checked = source_acl_checked_at(row.doc_metadata, now)
        if row.id.startswith("feishu:") and (
            checked is None or now - checked > ACL_MAX_AGE_SECONDS
        ):
            result[row.id] = ExternalAccess.empty()
            continue
        result[row.id] = ExternalAccess(
            external_user_emails=set(row.external_user_emails or []),
            external_user_group_ids=set(row.external_user_group_ids or []),
            is_public=False if row.id.startswith("feishu:") else row.is_public,
        )
    return result


def refresh_source_document_access(
    db_session: Session,
    document_access: dict[str, tuple[ExternalAccess, float | None]],
) -> dict[str, tuple[ExternalAccess, float | None]]:
    """Persist ACLs even when timestamp/content dedup skips embedding."""
    if not document_access:
        return {}
    resolved_access = dict(document_access)
    rows = db_session.scalars(
        select(Document).where(Document.id.in_(document_access))
    ).all()
    now = datetime.now(timezone.utc)
    for row in rows:
        access, checked = document_access[row.id]
        previous_checked = source_acl_checked_at(row.doc_metadata, now.timestamp())
        if (
            row.id.startswith("feishu:")
            and checked is not None
            and previous_checked is not None
            and previous_checked > checked
        ):
            resolved_access[row.id] = (
                ExternalAccess(
                    set(row.external_user_emails or []),
                    set(row.external_user_group_ids or []),
                    False,
                ),
                previous_checked,
            )
            continue
        row.external_user_emails = sorted(access.external_user_emails)
        row.external_user_group_ids = sorted(access.external_user_group_ids)
        row.is_public = access.is_public
        row.doc_metadata = {
            **(row.doc_metadata or {}),
            "orgmesh_acl_checked_at": checked,
        }
        row.last_modified = now
    db_session.commit()
    return resolved_access


def get_directory_membership(
    db_session: Session, email: str
) -> OrgMeshDirectoryUser | None:
    return db_session.get(OrgMeshDirectoryUser, email.lower())


def replace_directory_snapshot(
    db_session: Session, employees: list[tuple[str, str, list[str], bool]]
) -> int:
    """Apply a completed directory snapshot; never accept a partial crawl."""
    if not employees:
        raise ValueError("Empty directory snapshots require checking Feishu app scopes")
    db_session.execute(select(func.pg_advisory_xact_lock(73190630)))
    now = datetime.now(timezone.utc)
    emails = {item[0].lower() for item in employees}
    previous = db_session.scalars(select(OrgMeshDirectoryUser)).all()
    disabled = {row.email for row in previous if row.email not in emails}
    for email, employee_id, departments, active in employees:
        stmt = insert(OrgMeshDirectoryUser).values(
            email=email.lower(),
            employee_id=employee_id,
            department_ids=departments,
            active=active,
            expires_at=now + timedelta(seconds=ACL_MAX_AGE_SECONDS),
            updated_at=now,
        )
        db_session.execute(
            stmt.on_conflict_do_update(
                index_elements=[OrgMeshDirectoryUser.email],
                set_={
                    key: stmt.excluded[key]
                    for key in (
                        "employee_id",
                        "department_ids",
                        "active",
                        "expires_at",
                        "updated_at",
                    )
                },
            )
        )
        if not active:
            disabled.add(email.lower())
    if disabled:
        db_session.execute(
            update(OrgMeshDirectoryUser)
            .where(OrgMeshDirectoryUser.email.in_(disabled))
            .values(active=False, department_ids=[], expires_at=now)
        )
        # Never auto-reactivate an account disabled by an administrator.
        db_session.execute(
            update(User)
            .where(func.lower(User.email).in_(disabled))
            .values(is_active=False)
        )
    db_session.commit()
    return len(employees)


def directory_summary(db_session: Session) -> tuple[int, datetime | None]:
    count, last_sync = db_session.execute(
        select(
            func.count(OrgMeshDirectoryUser.email),
            func.max(OrgMeshDirectoryUser.updated_at),
        ).where(OrgMeshDirectoryUser.active.is_(True))
    ).one()
    return int(count), last_sync


def active_sso_provider_count(db_session: Session) -> int:
    from onyx.db.models import SSOProvider

    return int(
        db_session.scalar(
            select(func.count())
            .select_from(SSOProvider)
            .where(SSOProvider.enabled.is_(True))
        )
        or 0
    )


def get_protected_chat_document_ids(db_session: Session, session_id: UUID) -> list[str]:
    from onyx.db.models import (
        ChatMessage,
        ChatMessage__SearchDoc,
        SearchDoc,
        ToolCall,
        ToolCall__SearchDoc,
    )

    message_docs = db_session.scalars(
        select(SearchDoc.document_id)
        .join(
            ChatMessage__SearchDoc, SearchDoc.id == ChatMessage__SearchDoc.search_doc_id
        )
        .join(ChatMessage, ChatMessage.id == ChatMessage__SearchDoc.chat_message_id)
        .where(
            ChatMessage.chat_session_id == session_id,
            SearchDoc.document_id.like("feishu:%"),
        )
    ).all()
    tool_docs = db_session.scalars(
        select(SearchDoc.document_id)
        .join(ToolCall__SearchDoc, SearchDoc.id == ToolCall__SearchDoc.search_doc_id)
        .join(ToolCall, ToolCall.id == ToolCall__SearchDoc.tool_call_id)
        .where(
            ToolCall.chat_session_id == session_id,
            SearchDoc.document_id.like("feishu:%"),
        )
    ).all()
    return sorted(set(message_docs) | set(tool_docs))
