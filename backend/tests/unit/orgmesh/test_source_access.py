from onyx.access.models import DocumentAccess, ExternalAccess
from onyx.access.source_access import authoritative_source_access


def test_source_acl_never_inherits_connector_public_access() -> None:
    connector = DocumentAccess.build([], [], [], [], True)
    access = authoritative_source_access(
        connector, ExternalAccess({"employee@example.com"}, set(), False)
    )
    assert not access.is_public
    assert access.to_acl() == {"user_email:employee@example.com"}


def test_empty_source_acl_is_closed() -> None:
    connector = DocumentAccess.build(["owner@example.com"], [], [], [], True)
    assert (
        authoritative_source_access(connector, ExternalAccess.empty()).to_acl() == set()
    )


def test_absent_source_acl_preserves_existing_connector_behavior() -> None:
    connector = DocumentAccess.build(["owner@example.com"], [], [], [], False)
    assert authoritative_source_access(connector, None) == connector
