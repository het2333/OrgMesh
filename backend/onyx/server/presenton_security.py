"""Scoped tokens and path validation for the private Presenton bridge."""

import base64
import hashlib
import hmac
import json
import time
from urllib.parse import unquote
from uuid import UUID


def _encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


def issue_token(owner: UUID, audience: str, secret: str, ttl: int) -> str:
    if len(secret) < 32:
        raise ValueError("Bridge secret is not configured")
    now = int(time.time())
    payload = _encode(
        json.dumps(
            {"sub": str(owner), "aud": audience, "iat": now, "exp": now + ttl, "v": 1},
            separators=(",", ":"),
        ).encode()
    )
    return (
        payload
        + "."
        + _encode(hmac.new(secret.encode(), payload.encode(), hashlib.sha256).digest())
    )


def verify_token(
    token: str, audience: str, secret: str, now: int | None = None
) -> UUID:
    if len(secret) < 32 or len(token) > 2048:
        raise ValueError("Invalid bridge token")
    try:
        payload, signature = token.split(".")
        expected = _encode(
            hmac.new(secret.encode(), payload.encode(), hashlib.sha256).digest()
        )
        if not hmac.compare_digest(signature, expected):
            raise ValueError("Invalid signature")
        claims = json.loads(
            base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4))
        )
        timestamp = int(time.time()) if now is None else now
        if claims["v"] != 1 or claims["aud"] != audience:
            raise ValueError("Invalid audience")
        if not isinstance(claims["exp"], int) or not isinstance(claims["iat"], int):
            raise ValueError("Invalid time")
        if (
            claims["exp"] <= timestamp
            or claims["iat"] > timestamp + 30
            or not 0 < claims["exp"] - claims["iat"] <= 900
        ):
            raise ValueError("Token expired")
        return UUID(claims["sub"])
    except (KeyError, TypeError, UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError("Invalid bridge token") from exc


def validate_proxy_path(path: str, method: str = "GET") -> str:
    decoded = path
    for _ in range(3):
        decoded = unquote(decoded)
    if (
        path != decoded
        or any(part in (".", "..") for part in decoded.split("/"))
        or any(c in decoded for c in ("\\", ":", "\x00"))
        or decoded.startswith("/")
    ):
        raise ValueError("Invalid proxy path")
    if path.startswith(
        ("api/v1/ppt/template/", "api/v1/ppt/fonts/")
    ) and method not in ("GET", "HEAD"):
        raise ValueError("Shared template and font mutations are unavailable")
    if path == "api/v1/auth/status":
        return path
    if path.startswith("api/"):
        allowed = (
            "api/v1/ppt/presentation/",
            "api/v2/ppt/presentation/",
            "api/v1/ppt/chat/",
            "api/v1/ppt/slide/",
            "api/v1/ppt/files/",
            "api/v1/ppt/fonts/",
            "api/v1/ppt/icons/",
            "api/v1/ppt/images/",
            "api/v1/ppt/template/",
            "api/v1/async-tasks",
            "api/export-presentation",
            "api/layouts",
            "api/fonts",
            "api/update-svg",
            "api/read-file",
            "api/upload-image",
        )
        if not path.startswith(allowed) or any(
            item in path
            for item in (
                "webhook",
                "user-config",
                "provider",
                "presentation/generate",
                "presentation/create",
                "presentation/prepare",
                "presentation/derive",
            )
        ):
            raise ValueError("Route unavailable in embedded mode")
    elif not path.startswith(
        ("_next/", "static/", "app_data/", "fonts/", "images/", "assets/", "vendor/")
    ) and path not in ("presentation", "pdf-maker", "favicon.ico", "robots.txt", ""):
        # Public resources are constrained to extensions; pages remain embedded.
        if "/" in path or not path.endswith(
            (".svg", ".png", ".jpg", ".webp", ".woff2", ".js")
        ):
            raise ValueError("Route unavailable in embedded mode")
    return path
