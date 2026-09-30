import pytest

from onyx.access.directory import department_ancestors
from onyx.connectors.feishu.client import FeishuAPIError


def test_nested_departments_include_only_actual_ancestors() -> None:
    assert department_ancestors(
        ["team-a"], {"team-a": "division", "division": "0", "other": "0"}
    ) == ["division", "team-a"]


def test_department_cycles_are_denied() -> None:
    with pytest.raises(FeishuAPIError):
        department_ancestors(["a"], {"a": "b", "b": "a"})


def test_root_does_not_grant_all_company_departments() -> None:
    assert department_ancestors(["0"], {"team-a": "0"}) == []
