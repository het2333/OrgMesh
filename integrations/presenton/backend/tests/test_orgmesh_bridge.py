"""Verify the private identity exchange in the pinned Presenton runtime."""

import asyncio
import base64
import hashlib
import hmac
import importlib
import importlib.util
import json
import os
import tempfile
import time
import unittest
import uuid
from collections.abc import AsyncGenerator
from pathlib import Path
from typing import cast
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient
from httpx import Response
from sqlalchemy import Table
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

OWNER_ID = uuid.UUID("eedc6c15-b33e-4ac3-bd94-3dffcb335703")
SECRET = "test-native-bridge-secret-with-32-bytes"


def sign_fixture(claims: dict[str, object], secret: str = SECRET) -> str:
    payload = base64.urlsafe_b64encode(
        json.dumps(claims, separators=(",", ":")).encode()
    ).rstrip(b"=")
    signature = hmac.new(secret.encode(), payload, hashlib.sha256).digest()
    encoded_signature = base64.urlsafe_b64encode(signature).rstrip(b"=")
    return f"{payload.decode()}.{encoded_signature.decode()}"


def session_fixture(**changes: object) -> str:
    now = int(time.time())
    claims: dict[str, object] = {
        "sub": str(OWNER_ID),
        "aud": "orgmesh-presenton-session",
        "iat": now,
        "exp": now + 60,
        "v": 1,
    }
    claims.update(changes)
    return sign_fixture(claims)


class BridgeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.environment = patch.dict(
            os.environ,
            {
                "ORGMESH_PRESENTON_SECRET": SECRET,
                "USER_CONFIG_PATH": str(Path(self.directory.name) / "config.json"),
                "DATABASE_URL": "sqlite+aiosqlite:///:memory:",
                "LLM": "custom",
                "CUSTOM_MODEL": "orgmesh-default",
                "CUSTOM_LLM_URL": "http://api_server:8080/orgmesh/presenton/llm/v1",
                "CUSTOM_LLM_API_KEY": "unusable-global-key",
                "CAN_CHANGE_KEYS": "false",
                "DISABLE_AUTH": "false",
            },
        )
        self.environment.start()
        self.addCleanup(self.environment.stop)
        from api.v1.auth.router import API_V1_AUTH_ROUTER
        from models.sql.user import User
        from services.database import get_async_session

        self.engine = create_async_engine(
            f"sqlite+aiosqlite:///{self.directory.name}/bridge.db"
        )
        self.sessions = async_sessionmaker(self.engine, expire_on_commit=False)

        async def create_tables() -> None:
            async with self.engine.begin() as connection:
                await connection.run_sync(cast(Table, User.__table__).create)

        asyncio.run(create_tables())
        self.addCleanup(lambda: asyncio.run(self.engine.dispose()))

        async def session_override() -> AsyncGenerator[AsyncSession, None]:
            async with self.sessions() as session:
                yield session

        self.app = FastAPI()
        self.app.include_router(API_V1_AUTH_ROUTER)
        if importlib.util.find_spec("api.v1.orgmesh") is not None:
            bridge = importlib.import_module("api.v1.orgmesh")
            self.app.include_router(bridge.ORGMESH_ROUTER)
        self.app.dependency_overrides[get_async_session] = session_override
        self.client = TestClient(self.app)
        self.addCleanup(self.client.close)

    def exchange(self, token: str) -> Response:
        return self.client.post("/api/v1/orgmesh/session", json={"token": token})

    def test_exchange_creates_non_admin_native_owner_and_original_jwt(self) -> None:
        from api.v1.auth.users import (
            UserManager,
            UsernameUserDatabase,
            get_jwt_strategy,
        )
        from models.sql.user import User

        response = self.exchange(session_fixture())
        self.assertEqual(response.status_code, 200, response.text)
        payload = response.json()
        self.assertEqual(set(payload), {"token", "cookie_name"})
        self.assertEqual(payload["cookie_name"], "presenton_session")

        async def inspect_user() -> None:
            async with self.sessions() as session:
                user = await session.get(User, OWNER_ID)
                assert user is not None
                self.assertEqual(user.username, f"orgmesh_{OWNER_ID}")
                self.assertTrue(user.is_active)
                self.assertTrue(user.is_verified)
                self.assertFalse(user.is_superuser)
                self.assertIsNone(user.admin_slot)
                decoded = await get_jwt_strategy().read_token(
                    payload["token"], UserManager(UsernameUserDatabase(session))
                )
                assert decoded is not None
                self.assertEqual(decoded.id, OWNER_ID)

        asyncio.run(inspect_user())
        self.client.cookies.set(payload["cookie_name"], payload["token"])
        status = self.client.get("/api/v1/auth/status")
        self.assertEqual(status.status_code, 200)
        self.assertTrue(status.json()["authenticated"])
        self.assertEqual(status.json()["role"], "user")

    def test_exchange_rejects_forged_expired_and_wrong_audience_tokens(self) -> None:
        now = int(time.time())
        for token in (
            sign_fixture({"sub": str(OWNER_ID)}, "wrong-secret"),
            session_fixture(iat=now - 120, exp=now - 1),
            session_fixture(aud="orgmesh-presenton-llm"),
            session_fixture(iat=now + 60, exp=now + 120),
            session_fixture(exp=now + 3600),
            session_fixture(v=2),
            session_fixture(v=True),
            session_fixture(exp=str(now + 60)),
            session_fixture(sub="invalid-owner"),
            "malformed",
        ):
            with self.subTest(token_kind=token[:12]):
                response = self.exchange(token)
                self.assertEqual(response.status_code, 401, response.text)

    def test_exchange_is_idempotent_and_never_promotes_owner(self) -> None:
        from models.sql.user import User
        from sqlalchemy import func, select

        first = self.exchange(session_fixture())
        second = self.exchange(session_fixture())
        self.assertEqual(first.status_code, 200, first.text)
        self.assertEqual(second.status_code, 200, second.text)

        async def inspect_user() -> None:
            async with self.sessions() as session:
                self.assertEqual(
                    await session.scalar(select(func.count()).select_from(User)), 1
                )
                user = await session.get(User, OWNER_ID)
                assert user is not None
                self.assertFalse(user.is_superuser)

        asyncio.run(inspect_user())

    def test_exchange_cannot_overwrite_an_existing_original_account(self) -> None:
        from models.sql.user import User

        async def seed_original_user() -> None:
            async with self.sessions() as session:
                session.add(
                    User(
                        id=OWNER_ID,
                        username="original-admin",
                        hashed_password="unused",
                        is_superuser=True,
                    )
                )
                await session.commit()

        asyncio.run(seed_original_user())
        response = self.exchange(session_fixture())
        self.assertEqual(response.status_code, 409, response.text)

    def test_exchange_is_public_only_to_its_signed_request_before_setup(self) -> None:
        from api import middlewares

        self.app.add_middleware(middlewares.SessionAuthMiddleware)
        with patch.object(middlewares, "async_session_maker", self.sessions):
            response = self.exchange(session_fixture())
        self.assertEqual(response.status_code, 200, response.text)

    def test_custom_client_uses_owner_scoped_relay_token(self) -> None:
        from api.v1.auth.context import reset_current_owner_id, set_current_owner_id
        from utils.llm_config import get_llm_config

        context_token = set_current_owner_id(OWNER_ID)
        try:
            config = get_llm_config()
        finally:
            reset_current_owner_id(context_token)

        self.assertEqual(
            config.base_url, "http://api_server:8080/orgmesh/presenton/llm/v1"
        )
        parts = config.api_key.split(".")
        self.assertEqual(len(parts), 2, "Relay must use a signed owner token")
        expected_signature = hmac.new(
            SECRET.encode(), parts[0].encode(), hashlib.sha256
        ).digest()
        signature = base64.urlsafe_b64decode(parts[1] + "=" * (-len(parts[1]) % 4))
        self.assertTrue(hmac.compare_digest(expected_signature, signature))
        claims = json.loads(
            base64.urlsafe_b64decode(parts[0] + "=" * (-len(parts[0]) % 4))
        )
        self.assertEqual(claims["sub"], str(OWNER_ID))
        self.assertEqual(claims["aud"], "orgmesh-presenton-llm")
        self.assertEqual(claims["v"], 1)
        self.assertEqual(claims["exp"] - claims["iat"], 900)
        self.assertEqual(os.environ["CUSTOM_LLM_API_KEY"], "unusable-global-key")


if __name__ == "__main__":
    unittest.main()
