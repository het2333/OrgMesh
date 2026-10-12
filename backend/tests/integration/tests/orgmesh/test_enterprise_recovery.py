"""Operator-staged, real recovery acceptance without account or credential creation.

Run with --noconftest. The general harness can provision accounts and credentials.
Use the local frontend, existing authorized admin storage state, and seeded search data.
See docs/orgmesh-enterprise-phase1-operations.md for each explicit phase.
These tests never stop services, alter flags, change grants, or create a database.
"""

import json
import os
from collections.abc import Generator
from pathlib import Path
from typing import Any
from urllib.parse import urlparse
from uuid import uuid4

import httpx
import pytest

BASE = "/api/orgmesh-enterprise/v1"


def require_phase(*phases: str) -> None:
    phase = os.environ.get("ORGMESH_RECOVERY_PHASE")
    assert phase in phases, f"Operator must prepare phase {phases}; got {phase!r}"


def baseline_path() -> Path:
    name = os.environ.get("ORGMESH_RECOVERY_BASELINE_FILE")
    assert name, "Supply a dedicated recovery evidence JSON path"
    return Path(name)


def evidence() -> dict[str, Any]:
    return json.loads(baseline_path().read_text())


@pytest.fixture
def browser() -> Generator[httpx.Client, None, None]:
    origin = os.environ.get("BASE_URL", "http://localhost:3000")
    parsed = urlparse(origin)
    assert parsed.hostname in ("localhost", "127.0.0.1", "::1")
    assert parsed.path in ("", "/") and not parsed.username and not parsed.password
    auth = os.environ.get("ORGMESH_TEST_AUTH_STATE")
    assert auth, (
        "Supply an existing authorized admin Playwright storage state. No automatic sign-up or token creation."
    )
    state = json.loads(Path(auth).read_text())
    cookies = httpx.Cookies()
    for cookie in state["cookies"]:
        cookies.set(
            cookie["name"],
            cookie["value"],
            domain=cookie["domain"],
            path=cookie["path"],
        )
    with httpx.Client(
        base_url=origin,
        cookies=cookies,
        timeout=30,
        trust_env=False,
        follow_redirects=False,
    ) as client:
        context = client.get(f"{BASE}/context")
        assert context.status_code == 200, (
            "Existing session must be an authorized global admin"
        )
        yield client


def test_branding_without_audit_ui_still_records(browser: httpx.Client) -> None:
    require_phase("branding-no-audit")
    capabilities = browser.get(f"{BASE}/capabilities").json()
    assert capabilities["branding_enabled"] is True
    assert capabilities["audit_enabled"] is False
    original = browser.get(f"{BASE}/branding").json()
    key = str(uuid4())
    response = browser.patch(
        f"{BASE}/branding",
        json={
            "expected_version": original["version"],
            "name": f"Recovery {key[:8]}",
            "greeting": original["greeting"],
            "logo_asset_id": original["logo_asset_id"],
        },
        headers={"Idempotency-Key": key},
    )
    assert response.status_code == 200
    changed = response.json()
    assert changed["version"] == original["version"] + 1
    assert browser.get(f"{BASE}/audit/events").status_code == 503
    baseline_path().write_text(
        json.dumps(
            {"original_brand": original, "changed_brand": changed, "key": key}, indent=2
        )
    )


def test_audit_survives_ui_reenable_and_capture_snapshot(browser: httpx.Client) -> None:
    require_phase("enabled")
    saved = evidence()
    capabilities = browser.get(f"{BASE}/capabilities").json()
    assert all(
        capabilities[field]
        for field in ("branding_enabled", "audit_enabled", "usage_enabled")
    )
    audit = browser.get(f"{BASE}/audit/events")
    assert audit.status_code == 200
    assert any(
        event["after_version"] == saved["changed_brand"]["version"]
        and event["result"] == "success"
        for event in audit.json()["events"]
    )
    summary = browser.get(f"{BASE}/usage/summary")
    assert summary.status_code == 200 and summary.json()["status"] in ("ready", "stale")
    saved["usage"] = summary.json()
    assert saved["usage"]["coverage"] is not None
    baseline_path().write_text(json.dumps(saved, indent=2))


def test_disabled_features_no_source_reads(browser: httpx.Client) -> None:
    require_phase("disabled")
    assert browser.get(f"{BASE}/capabilities").json() == {
        "branding_enabled": False,
        "audit_enabled": False,
        "usage_enabled": False,
        "static_branding_version": 1,
    }
    assert browser.get(f"{BASE}/branding").json()["source"] == "static"
    assert browser.get(f"{BASE}/audit/events").status_code == 503
    assert browser.get(f"{BASE}/usage/summary").status_code == 503
    # Source-open suppression is proved by the offline producer guard test.
    # This real phase verifies the externally visible disabled API boundary.


def test_outage_does_not_break_chat(browser: httpx.Client) -> None:
    require_phase("go-outage", "db-outage", "disabled")
    static_file = os.environ.get("ORGMESH_RECOVERY_EXPECTED_STATIC_FILE")
    assert static_file, (
        "Supply the approved static branding JSON used by the deployment"
    )
    expected_brand = json.loads(Path(static_file).read_text()) | {
        "version": 0,
        "source": "static",
    }
    response = browser.get(f"{BASE}/branding")
    assert response.status_code == 200 and response.json() == expected_brand
    assert os.environ.get("ORGMESH_RECOVERY_MOCK_LLM_APPROVED") == "true", (
        "Use only a verified integration-mode mock provider. No real LLM key is needed."
    )
    answer = "OrgMesh recovery mock answer"
    chat = browser.post(
        "/api/chat/send-chat-message",
        json={
            "message": "Recovery smoke test",
            "mock_llm_response": answer,
            "allowed_tool_ids": [],
            "stream": False,
        },
    )
    assert chat.status_code == 200, chat.text[:300]
    assert answer in chat.text
    expected_document = os.environ.get("ORGMESH_RECOVERY_SEARCH_DOCUMENT_ID")
    assert expected_document, (
        "Seed the existing search fixture before recovery acceptance"
    )
    search = browser.post(
        "/api/admin/search", json={"query": "orgmesh recovery fixture", "filters": {}}
    )
    assert search.status_code == 200
    assert any(
        document["document_id"] == expected_document
        for document in search.json()["documents"]
    )


def test_reenable_no_double_count(browser: httpx.Client) -> None:
    require_phase("reenabled")
    before = evidence()
    current_brand = browser.get(f"{BASE}/branding")
    assert (
        current_brand.status_code == 200
        and current_brand.json() == before["changed_brand"]
    )
    coverage = before["usage"]["coverage"]
    response = browser.get(
        f"{BASE}/usage/summary",
        params={
            "start": coverage["from"],
            "end": coverage["to"],
            "group_by": before["usage"]["group_by"],
        },
    )
    assert response.status_code == 200
    current = response.json()
    assert current["status"] in ("ready", "stale")
    assert current["revision"] >= before["usage"]["revision"]
    assert current["groups"] == before["usage"]["groups"], (
        "Keep the seeded source unchanged during replay"
    )
