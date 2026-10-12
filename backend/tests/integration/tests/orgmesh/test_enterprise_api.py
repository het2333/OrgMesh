"""Use a real Community app, database, and private Go usage service.

Enable ORGMESH_ENTERPRISE_USAGE_ENABLED in the isolated test deployment.
No model/provider call is needed. Missing prerequisites fail this suite.
Use an approved isolated deployment with authorized test authentication fixtures.
Supply an existing restricted admin PAT through the test environment.
This file creates no PAT. Credential provisioning needs separate explicit approval.
"""

import os
from datetime import datetime, timedelta, timezone

import pytest

from onyx.orgmesh_enterprise.models import UsageSummary
from tests.integration.common_utils.constants import API_SERVER_URL
from tests.integration.common_utils.http_client import client
from tests.integration.common_utils.test_models import DATestUser

BASE = f"{API_SERVER_URL}/orgmesh-enterprise/v1"


def test_usage_requires_authenticated_global_admin(
    admin_user: DATestUser, basic_user: DATestUser
) -> None:
    assert client.get(f"{BASE}/usage/summary", timeout=10).status_code == 401
    assert (
        client.get(
            f"{BASE}/usage/summary",
            headers=basic_user.headers,
            cookies=basic_user.cookies,
            timeout=10,
        ).status_code
        == 403
    )
    capability = client.get(f"{BASE}/capabilities", timeout=10)
    capability.raise_for_status()
    assert capability.json()["usage_enabled"] is True, (
        "Enable usage in the isolated test deployment"
    )
    response = client.get(
        f"{BASE}/usage/summary",
        headers=admin_user.headers,
        cookies=admin_user.cookies,
        timeout=10,
    )
    response.raise_for_status()
    summary = UsageSummary.model_validate_json(response.content)
    assert summary.group_by == "day"
    assert summary.status in ("ready", "stale", "waiting", "unavailable")
    assert "0 may mean missing pricing" in summary.cost_notice
    assert all(
        key not in response.text for key in ('"user_id"', '"source_row_id"', '"email"')
    )


@pytest.mark.parametrize(
    "query",
    [
        "tenant_id=other",
        "organization=other",
        "group_by=user_id",
        "start=2026-10-12T12%3A00%3A00Z",
        "future_end",
    ],
)
def test_usage_rejects_browser_organization_and_invalid_daily_ranges(
    admin_user: DATestUser, query: str
) -> None:
    if query == "future_end":
        today = datetime.now(timezone.utc).replace(
            hour=0, minute=0, second=0, microsecond=0
        )
        query = "end=" + (today + timedelta(days=2)).isoformat().replace("+", "%2B")
    response = client.get(
        f"{BASE}/usage/summary?{query}",
        headers=admin_user.headers,
        cookies=admin_user.cookies,
        timeout=10,
    )
    assert response.status_code == 422


@pytest.mark.parametrize("dimension", ["day", "model", "flow"])
def test_usage_dimensions_have_named_grouped_contract(
    admin_user: DATestUser, dimension: str
) -> None:
    today = datetime.now(timezone.utc).replace(
        hour=0, minute=0, second=0, microsecond=0
    )
    response = client.get(
        f"{BASE}/usage/summary",
        params={
            "start": today.isoformat(),
            "end": (today + timedelta(days=1)).isoformat(),
            "group_by": dimension,
        },
        headers=admin_user.headers,
        cookies=admin_user.cookies,
        timeout=10,
    )
    response.raise_for_status()
    result = UsageSummary.model_validate_json(response.content)
    assert result.group_by == dimension
    assert all(
        int(group.totals.total_tokens)
        == int(group.totals.input_tokens) + int(group.totals.output_tokens)
        for group in result.groups
    )


def test_existing_restricted_admin_pat_cannot_read_usage() -> None:
    token = os.environ.get("ORGMESH_ENTERPRISE_TEST_RESTRICTED_ADMIN_PAT")
    if not token:
        pytest.fail(
            "Supply an existing restricted admin test PAT in "
            "ORGMESH_ENTERPRISE_TEST_RESTRICTED_ADMIN_PAT. "
            "Credential provisioning requires separate approval in the isolated deployment."
        )
    response = client.get(
        f"{BASE}/usage/summary",
        headers={"Authorization": f"Bearer {token}"},
        timeout=10,
    )
    assert response.status_code == 403
