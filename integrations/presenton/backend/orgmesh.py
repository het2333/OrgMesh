"""Exchange trusted native identities for original Presenton sessions."""

import secrets
import uuid

from api.v1.auth.config import SESSION_COOKIE_NAME
from api.v1.auth.users import PASSWORD_HELPER, get_jwt_strategy
from fastapi import APIRouter, Depends, HTTPException
from models.sql.user import User
from pydantic import BaseModel, ConfigDict, Field
from services.database import get_async_session
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from utils.orgmesh_tokens import (
    SESSION_AUDIENCE,
    BridgeNotConfiguredError,
    BridgeTokenError,
    verify_bridge_token,
)

ORGMESH_ROUTER = APIRouter(prefix="/api/v1/orgmesh", tags=["Native integration"])
SESSION_LIFETIME_SECONDS = 3600


class NativeSessionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    token: str = Field(min_length=1, max_length=4096)


class NativeSessionResponse(BaseModel):
    token: str
    cookie_name: str


async def _upsert_native_user(session: AsyncSession, owner_id: uuid.UUID) -> User:
    username = f"orgmesh_{owner_id}"
    user = await session.get(User, owner_id)
    if user is None:
        user = User(
            id=owner_id,
            username=username,
            hashed_password=PASSWORD_HELPER.hash(secrets.token_urlsafe(48)),
            is_active=True,
            is_verified=True,
            is_superuser=False,
            admin_slot=None,
            auth_version=1,
        )
        session.add(user)
        try:
            await session.commit()
        except IntegrityError:
            # Two native requests can exchange the same identity together.
            await session.rollback()
            user = await session.get(User, owner_id)
            if user is None:
                raise HTTPException(status_code=409, detail="Native account conflict")

    if user.username != username:
        raise HTTPException(status_code=409, detail="Native account conflict")

    if (
        not user.is_active
        or not user.is_verified
        or user.is_superuser
        or user.admin_slot
    ):
        user.is_active = True
        user.is_verified = True
        user.is_superuser = False
        user.admin_slot = None
        user.auth_version += 1
        session.add(user)
        await session.commit()
    return user


@ORGMESH_ROUTER.post("/session", include_in_schema=False)
async def exchange_native_session(
    request: NativeSessionRequest,
    session: AsyncSession = Depends(get_async_session),
) -> NativeSessionResponse:
    try:
        claims = verify_bridge_token(request.token, SESSION_AUDIENCE)
    except BridgeNotConfiguredError as error:
        raise HTTPException(
            status_code=503, detail="Native integration is not configured"
        ) from error
    except BridgeTokenError as error:
        raise HTTPException(
            status_code=401, detail="Invalid native identity"
        ) from error

    user = await _upsert_native_user(session, claims.sub)
    token = await get_jwt_strategy(SESSION_LIFETIME_SECONDS).write_token(user)
    return NativeSessionResponse(token=token, cookie_name=SESSION_COOKIE_NAME)
