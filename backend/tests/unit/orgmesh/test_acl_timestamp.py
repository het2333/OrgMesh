import math

import pytest

from onyx.access.source_access import source_acl_checked_at


def test_acl_age_starts_when_permissions_are_fetched() -> None:
    assert source_acl_checked_at({"orgmesh_acl_checked_at": 1000.0}, 2000.0) == 1000.0


@pytest.mark.parametrize("value", [None, True, "1000", math.nan, math.inf, 2061.0])
def test_missing_invalid_or_future_acl_time_is_denied(value: object) -> None:
    assert source_acl_checked_at({"orgmesh_acl_checked_at": value}, 2000.0) is None
