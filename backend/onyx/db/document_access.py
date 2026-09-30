"""SQL filters matching indexed document visibility."""

from uuid import UUID

from sqlalchemy import (
    Numeric,
    Select,
    String,
    and_,
    any_,
    case,
    cast,
    false,
    func,
    literal,
    or_,
    select,
)
from sqlalchemy.dialects import postgresql
from sqlalchemy.orm import Session
from sqlalchemy.sql.elements import ColumnElement

from onyx.db.connector_credential_pair import build_user_cc_pair_access_filter
from onyx.db.enums import AccessType, AccountType, ConnectorCredentialPairStatus
from onyx.db.models import (
    ConnectorCredentialPair,
    Document,
    DocumentByConnectorCredentialPair,
    OrgMeshDirectoryUser,
    User,
)
from onyx.db.orgmesh import ACL_MAX_AGE_SECONDS


def _feishu_source_access_filter(user_id: UUID | None) -> ColumnElement[bool]:
    if user_id is None:
        return false()
    checked_value = Document.doc_metadata["orgmesh_acl_checked_at"]
    checked_at = case(
        (
            func.jsonb_typeof(checked_value) == "number",
            cast(checked_value.astext, Numeric),
        ),
        else_=None,
    )
    now = func.extract("epoch", func.now())
    departments = (
        func.unnest(OrgMeshDirectoryUser.department_ids)
        .table_valued("department_id")
        .render_derived(name="feishu_department")
    )
    department_access = (
        select(literal(1))
        .select_from(departments)
        .where(
            any_(Document.external_user_group_ids)
            == literal("feishu:department:") + departments.c.department_id
        )
        .correlate(Document, OrgMeshDirectoryUser)
        .exists()
    )
    directory_access = (
        select(literal(1))
        .select_from(User)
        .join(
            OrgMeshDirectoryUser, OrgMeshDirectoryUser.email == func.lower(User.email)
        )
        .where(
            User.__table__.c.id == user_id,
            User.__table__.c.is_active.is_(True),
            User.__table__.c.is_verified.is_(True),
            User.account_type != AccountType.ANONYMOUS,
            OrgMeshDirectoryUser.active.is_(True),
            OrgMeshDirectoryUser.expires_at > func.now(),
            or_(
                any_(Document.external_user_emails) == func.lower(User.email),
                department_access,
            ),
        )
        .correlate(Document)
        .exists()
    )
    return and_(
        checked_at.is_not(None),
        checked_at >= now - ACL_MAX_AGE_SECONDS,
        checked_at <= now + 60,
        directory_access,
    )


def apply_document_access_filter(
    stmt: Select,
    user_email: str | None,
    external_group_ids: list[str],
    user_id: UUID | None = None,
) -> Select:
    """Filter documents by source ACL or associated connector access."""
    stmt = stmt.join(
        DocumentByConnectorCredentialPair,
        Document.id == DocumentByConnectorCredentialPair.id,
    ).join(
        ConnectorCredentialPair,
        and_(
            DocumentByConnectorCredentialPair.connector_id
            == ConnectorCredentialPair.connector_id,
            DocumentByConnectorCredentialPair.credential_id
            == ConnectorCredentialPair.credential_id,
        ),
    )

    stmt = stmt.where(
        ConnectorCredentialPair.status != ConnectorCredentialPairStatus.DELETING
    )

    access_filters: list[ColumnElement[bool]] = [
        ConnectorCredentialPair.access_type == AccessType.PUBLIC,
        Document.is_public.is_(True),
    ]
    if user_email:
        access_filters.append(any_(Document.external_user_emails) == user_email)
    if external_group_ids:
        access_filters.append(
            Document.external_user_group_ids.overlap(
                cast(postgresql.array(external_group_ids), postgresql.ARRAY(String))
            )
        )
    if user_id:
        access_filters.append(build_user_cc_pair_access_filter(user_id))

    # Source ACLs govern Feishu before cursor pagination or connector sharing.
    is_feishu = Document.id.like("feishu:%")
    return stmt.where(
        or_(
            and_(~is_feishu, or_(*access_filters)),
            and_(is_feishu, _feishu_source_access_filter(user_id)),
        )
    )


def get_accessible_documents_by_ids(
    db_session: Session,
    document_ids: list[str],
    user_email: str | None,
    external_group_ids: list[str],
    user_id: UUID | None = None,
) -> list[Document]:
    """Return requested documents allowed by the retrieval-time access policy."""
    if not document_ids:
        return []

    stmt = select(Document).where(Document.id.in_(document_ids))
    stmt = apply_document_access_filter(
        stmt, user_email, external_group_ids, user_id=user_id
    )
    stmt = stmt.distinct()
    documents: list[Document] = list(db_session.execute(stmt).scalars().all())
    user = db_session.get(User, user_id) if user_id is not None else None
    if user is None:
        return [doc for doc in documents if not doc.id.startswith("feishu:")]

    # Local import avoids the access -> document -> document_access import cycle.
    from onyx.access.access import filter_authorized_document_ids

    allowed_ids = filter_authorized_document_ids(
        [doc.id for doc in documents], user, db_session
    )
    return [doc for doc in documents if doc.id in allowed_ids]
