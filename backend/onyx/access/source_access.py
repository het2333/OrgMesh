import math

from onyx.access.models import DocumentAccess, ExternalAccess


def authoritative_source_access(
    connector_access: DocumentAccess, source_access: ExternalAccess | None
) -> DocumentAccess:
    """A source ACL replaces connector sharing, including an empty ACL."""
    if source_access is None:
        return connector_access
    return DocumentAccess.build(
        user_emails=[],
        user_groups=[],
        external_user_emails=sorted(source_access.external_user_emails),
        external_user_group_ids=sorted(source_access.external_user_group_ids),
        is_public=source_access.is_public,
    )


def source_acl_checked_at(additional_info: object, now: float) -> float | None:
    """Retain the source fetch time across queues; allow 60 seconds of clock skew."""
    if not isinstance(additional_info, dict):
        return None
    checked = additional_info.get("orgmesh_acl_checked_at")
    if (
        isinstance(checked, bool)
        or not isinstance(checked, (int, float))
        or not math.isfinite(checked)
        or checked > now + 60
    ):
        return None
    return float(checked)
