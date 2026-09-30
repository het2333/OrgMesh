"""Signed identities shared only by the native gateway and private Presenton."""

import base64
import binascii
import hashlib
import hmac
import os
import time
import uuid
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, StrictInt, ValidationError

SESSION_AUDIENCE = "orgmesh-presenton-session"
LLM_AUDIENCE = "orgmesh-presenton-llm"
TOKEN_LIFETIME_SECONDS = 900
MAX_TOKEN_LENGTH = 4096
CLOCK_SKEW_SECONDS = 30


class BridgeTokenError(ValueError):
    """The signed native identity cannot be accepted."""


class BridgeNotConfiguredError(ValueError):
    """The private native bridge has no deployment secret."""


class BridgeClaims(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    sub: uuid.UUID
    aud: Literal["orgmesh-presenton-session", "orgmesh-presenton-llm"]
    iat: StrictInt
    exp: StrictInt
    v: StrictInt = Field(ge=1, le=1)


def is_orgmesh_bridge_configured() -> bool:
    return bool(os.environ.get("ORGMESH_PRESENTON_SECRET"))


def _secret() -> bytes:
    value = os.environ.get("ORGMESH_PRESENTON_SECRET", "").encode("utf-8")
    if len(value) < 32:
        raise BridgeNotConfiguredError("Native bridge secret is not configured")
    return value


def _encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


def _decode(value: str) -> bytes:
    return base64.b64decode(
        value + "=" * (-len(value) % 4), altchars=b"-_", validate=True
    )


def verify_bridge_token(token: str, audience: str) -> BridgeClaims:
    secret = _secret()
    if not token or len(token) > MAX_TOKEN_LENGTH:
        raise BridgeTokenError("Invalid native identity")
    try:
        encoded_claims, encoded_signature = token.split(".")
        signature = _decode(encoded_signature)
        expected = hmac.new(
            secret, encoded_claims.encode("ascii"), hashlib.sha256
        ).digest()
        if not hmac.compare_digest(signature, expected):
            raise BridgeTokenError("Invalid native identity")
        claims = BridgeClaims.model_validate_json(_decode(encoded_claims))
    except (ValueError, UnicodeError, binascii.Error, ValidationError) as error:
        raise BridgeTokenError("Invalid native identity") from error

    now = int(time.time())
    if (
        claims.aud != audience
        or claims.exp <= now
        or claims.iat > now + CLOCK_SKEW_SECONDS
        or claims.exp <= claims.iat
        or claims.exp - claims.iat > TOKEN_LIFETIME_SECONDS
    ):
        raise BridgeTokenError("Invalid native identity")
    return claims


def issue_llm_relay_token(owner_id: uuid.UUID) -> str:
    now = int(time.time())
    claims = BridgeClaims(
        sub=owner_id,
        aud=LLM_AUDIENCE,
        iat=now,
        exp=now + TOKEN_LIFETIME_SECONDS,
        v=1,
    )
    payload = _encode(claims.model_dump_json().encode("utf-8"))
    signature = hmac.new(_secret(), payload.encode("ascii"), hashlib.sha256).digest()
    return f"{payload}.{_encode(signature)}"
