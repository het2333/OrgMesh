import time
from uuid import uuid4

import pytest

from onyx.server.presenton_security import (
    issue_token,
    validate_proxy_path,
    verify_token,
)

SECRET = "x" * 48


def test_bridge_token_is_scoped_and_expires():
    owner = uuid4()
    token = issue_token(owner, "orgmesh-presenton-session", SECRET, 60)
    assert verify_token(token, "orgmesh-presenton-session", SECRET) == owner
    for audience, secret in [
        ("orgmesh-presenton-llm", SECRET),
        ("orgmesh-presenton-session", "y" * 48),
    ]:
        with pytest.raises(ValueError):
            verify_token(token, audience, secret)
    with pytest.raises(ValueError):
        verify_token(
            token, "orgmesh-presenton-session", SECRET, now=int(time.time()) + 61
        )
    with pytest.raises(ValueError):
        verify_token(token + "x", "orgmesh-presenton-session", SECRET)


@pytest.mark.parametrize(
    "path",
    [
        "../api",
        "api/v1/ppt/openai/models/available",
        "api/v1/ppt/ollama/models/available",
        "api/v1/ppt/codex-auth/status",
        "api/v1/ppt/generation/config",
        "api/v1/ppt/presentation/generate",
        "api/v2/ppt/presentation/generate/smart",
        "api/v1/ppt/presentation/create",
        "api/v1/ppt/presentation/prepare",
        "api/v1/auth/setup",
        "api/v1/orgmesh/session",
        "api/v1/admin/users",
        "api/user-config",
        "http://evil",
        "app_data/../secret",
        "api/v1/ppt/webhook",
        "%252e%252e/foo",
        "api/v1/ppt/presentation/generate/async",
    ],
)
def test_proxy_blocks_privilege_and_traversal(path):
    with pytest.raises(ValueError):
        validate_proxy_path(path)


@pytest.mark.parametrize(
    "path",
    [
        "api/v1/auth/status",
        "presentation",
        "_next/static/js/main.js",
        "api/v1/ppt/presentation/update",
        "app_data/exports/users/a/test.pptx",
        "api/export-presentation/file",
    ],
)
def test_proxy_allows_editor_and_owned_assets(path):
    assert validate_proxy_path(path) == path


def test_presenton_routes_pass_platform_auth_audit():
    from fastapi import FastAPI
    from onyx.server.auth_check import check_router_auth
    from onyx.server.presenton import router

    app = FastAPI(openapi_url=None, docs_url=None, redoc_url=None)
    app.include_router(router)
    check_router_auth(app)


def test_proxy_denies_template_and_shared_font_mutations():
    for path in [
        "api/v1/ppt/template/fonts-upload-and-slides-preview",
        "api/v1/ppt/fonts/upload",
    ]:
        with pytest.raises(ValueError):
            validate_proxy_path(path, "POST")
    assert (
        validate_proxy_path("api/v1/ppt/template/all", "GET")
        == "api/v1/ppt/template/all"
    )
