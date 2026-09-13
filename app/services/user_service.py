import uuid

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import ConflictError, NotFoundError
from app.core.security import hash_password
from app.models.user import AppUser
from app.schemas.user import UserCreate, UserUpdate

#: app_user is deliberately not audited (no updated_by column), unlike
#: client/service_type/task_template.


async def load_user(session: AsyncSession, user_id: uuid.UUID) -> AppUser:
    result = await session.execute(
        select(AppUser).where(AppUser.id == user_id, AppUser.deleted_at.is_(None))
    )
    user = result.scalar_one_or_none()
    if user is None:
        raise NotFoundError("User not found")
    return user


async def list_users(session: AsyncSession) -> list[AppUser]:
    result = await session.execute(
        select(AppUser).where(AppUser.deleted_at.is_(None)).order_by(AppUser.full_name)
    )
    return list(result.scalars().all())


async def create_user(session: AsyncSession, payload: UserCreate) -> AppUser:
    user = AppUser(
        email=payload.email,
        full_name=payload.full_name,
        hashed_password=hash_password(payload.password),
        role=payload.role,
        is_active=True,
    )
    session.add(user)
    try:
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        if "app_user_email_key" in str(exc.orig):
            raise ConflictError("A user with that email already exists") from exc
        raise
    await session.refresh(user)
    return user


async def update_user(
    session: AsyncSession, user_id: uuid.UUID, payload: UserUpdate
) -> AppUser:
    user = await load_user(session, user_id)

    for field_name, value in payload.model_dump(exclude_unset=True).items():
        setattr(user, field_name, value)
    await session.commit()
    await session.refresh(user)
    return user
