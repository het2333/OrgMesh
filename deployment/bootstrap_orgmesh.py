"""Create a local workspace owner through the supported Onyx APIs."""

import http.cookiejar
import json
import os
from pathlib import Path
import secrets
import urllib.error
import urllib.parse
import urllib.request


ROOT = Path(__file__).resolve().parents[1]
PRIVATE = ROOT / ".orgmesh-local"
BASE_URL = "http://localhost:3090/api"


def save_private(path: Path, content: str) -> None:
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    os.fchmod(fd, 0o600)
    with os.fdopen(fd, "w") as stream:
        stream.write(content)


def main() -> None:
    PRIVATE.mkdir(mode=0o700, exist_ok=True)
    PRIVATE.chmod(0o700)
    account_path = PRIVATE / "owner.json"
    opener = urllib.request.build_opener(
        urllib.request.ProxyHandler({}),
        urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()),
    )

    def request(path: str, method: str = "GET", data: dict | None = None,
                form: bool = False) -> dict | list | None:
        body = None
        headers = {}
        if data is not None:
            body = (urllib.parse.urlencode(data) if form else json.dumps(data)).encode()
            headers["Content-Type"] = (
                "application/x-www-form-urlencoded" if form else "application/json"
            )
        req = urllib.request.Request(BASE_URL + path, body, headers, method=method)
        with opener.open(req, timeout=60) as response:
            payload = response.read()
            return json.loads(payload) if payload else None

    if account_path.exists():
        account = json.loads(account_path.read_text())
    else:
        metadata = request("/auth/type")
        if not isinstance(metadata, dict) or metadata.get("has_users"):
            raise RuntimeError("An existing account needs local owner credentials.")
        account = {
            "email": "orgmesh-local@example.com",
            "password": "Om!7" + secrets.token_urlsafe(36),
        }
        save_private(account_path, json.dumps(account))

    try:
        request("/auth/register", "POST", {
            "email": account["email"], "password": account["password"],
        })
    except urllib.error.HTTPError as error:
        detail = error.read()
        if error.code != 400 or b"REGISTER_USER_ALREADY_EXISTS" not in detail:
            raise RuntimeError(f"Owner registration failed (HTTP {error.code}).") from None

    request("/auth/login", "POST", {
        "username": account["email"], "password": account["password"],
    }, form=True)
    user = request("/me")
    if not isinstance(user, dict) or not user.get("admin_capabilities"):
        raise RuntimeError("The local owner must have workspace admin access.")

    token_path = PRIVATE / "pat.json"
    if token_path.exists():
        token = json.loads(token_path.read_text())
        active_tokens = request("/user/pats")
        if not isinstance(active_tokens, list) or not any(
            item["id"] == token["id"] for item in active_tokens
        ):
            token = None
    else:
        token = None
    if token is None:
        token = request("/user/pats", "POST", {
            "name": "OrgMesh local workspace", "expiration_days": None, "scopes": None,
        })
        save_private(token_path, json.dumps(token))

    save_private(PRIVATE / "access.inc",
                 f'proxy_set_header Authorization "Bearer {token["token"]}";\n')
    request("/user/language", "PATCH", {"language": "zh"})
    request("/user/theme-preference", "PATCH", {"theme_preference": "light"})
    if not (user.get("personalization") or {}).get("name"):
        request("/user/personalization", "PATCH", {"name": "OrgMesh"})
    print("Local owner and private gateway include are ready. No credentials were printed.")


if __name__ == "__main__":
    main()
