import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AuthenticationError
from app.core.security import (
    REFRESH_TOKEN_TYPE,
    create_access_token,
    create_refresh_token,
    decode_token,
    verify_password,
)
from app.models.user import AppUser


async def authenticate_user(
    session: AsyncSession, email: str, password: str
) -> AppUser:
    result = await session.execute(
        select(AppUser).where(AppUser.email == email, AppUser.deleted_at.is_(None))
    )
    user = result.scalar_one_or_none()

    # Verify even when the user is missing, so a wrong email and a wrong
    # password take the same time and cannot be told apart.
    hashed = user.hashed_password if user else "$2b$12$" + "x" * 53
    password_matches = verify_password(password, hashed)

    if user is None or not password_matches or not user.is_active:
        raise AuthenticationError("Incorrect email or password")
    return user


def issue_tokens(user: AppUser) -> tuple[str, str]:
    return create_access_token(user.id, user.role), create_refresh_token(user.id)


async def refresh_access_token(session: AsyncSession, refresh_token: str) -> tuple[str, str]:
    """The one authenticated path that does hit the database.

    Running once per token lifetime rather than once per request, it is where a
    deactivated or demoted user stops being able to act.
    """
    payload = decode_token(refresh_token)
    if payload.token_type != REFRESH_TOKEN_TYPE:
        raise AuthenticationError("Not a refresh token")

    result = await session.execute(
        select(AppUser).where(
            AppUser.id == payload.user_id, AppUser.deleted_at.is_(None)
        )
    )
    user = result.scalar_one_or_none()
    if user is None or not user.is_active:
        raise AuthenticationError("User is no longer active")
    return issue_tokens(user)
