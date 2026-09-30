"""Keep native account ownership after the private service restarts."""

import os
import unittest
import uuid
from typing import cast
from unittest.mock import patch

from api.v1.auth import bootstrap
from models.sql.user import User
from sqlalchemy import Table
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine


class NativeBootstrapTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.engine = create_async_engine("sqlite+aiosqlite:///:memory:")
        self.sessions = async_sessionmaker(self.engine, expire_on_commit=False)
        self.owner_id = uuid.uuid4()
        async with self.engine.begin() as connection:
            await connection.run_sync(cast(Table, User.__table__).create)
        async with self.sessions() as session:
            session.add(
                User(
                    id=self.owner_id,
                    username=f"orgmesh_{self.owner_id}",
                    hashed_password="unusable-test-password",
                    is_active=True,
                    is_verified=True,
                    is_superuser=False,
                    auth_version=1,
                )
            )
            await session.commit()

    async def asyncTearDown(self) -> None:
        await self.engine.dispose()

    async def run_bootstrap(self, secret: str) -> None:
        with (
            patch.object(bootstrap, "async_session_maker", self.sessions),
            patch.dict(
                os.environ,
                {
                    "ORGMESH_PRESENTON_SECRET": secret,
                    "AUTH_USERNAME": "",
                    "AUTH_PASSWORD": "",
                    "RESET_AUTH": "",
                    "AUTH_OVERRIDE_FROM_ENV": "",
                },
            ),
        ):
            await bootstrap.bootstrap_database_admin()

    async def test_restart_keeps_native_user_without_upstream_admin(self) -> None:
        await self.run_bootstrap("test-native-bridge-secret-with-32-bytes")
        async with self.sessions() as session:
            user = await session.get(User, self.owner_id)
        self.assertIsNotNone(user)
        assert user is not None
        self.assertFalse(user.is_superuser)
        self.assertIsNone(user.admin_slot)

    async def test_standalone_bootstrap_still_requires_admin(self) -> None:
        with self.assertRaisesRegex(RuntimeError, "no bootstrap administrator"):
            await self.run_bootstrap("")


if __name__ == "__main__":
    unittest.main()
