import uuid

from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import CurrentUser, get_current_user, require_admin, require_any_role
from app.database import get_session
from app.models.user import AppUser
from app.schemas.auth import CurrentUserResponse
from app.schemas.user import UserCreate, UserResponse, UserUpdate
from app.services import user_service

router = APIRouter(prefix="/api/v1", tags=["users"])


@router.get("/me", response_model=CurrentUserResponse)
async def read_me(
    current_user: CurrentUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> AppUser:
    return await user_service.load_user(session, current_user.id)


@router.get("/users", response_model=list[UserResponse])
async def list_users(
    _: CurrentUser = Depends(require_any_role),
    session: AsyncSession = Depends(get_session),
) -> list[AppUser]:
    """Readable by every authenticated role: it is a staff directory.

    Assignment needs it (a manager cannot pick an assignee from a list they
    cannot read) and every screen that shows a person's name needs it, since
    task and engagement responses carry ids rather than names. Creating and
    updating users remain admin-only just below.
    """
    return await user_service.list_users(session)


@router.post("/users", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
async def create_user(
    payload: UserCreate,
    current_user: CurrentUser = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
) -> AppUser:
    return await user_service.create_user(session, payload)


@router.patch("/users/{user_id}", response_model=UserResponse)
async def update_user(
    user_id: uuid.UUID,
    payload: UserUpdate,
    current_user: CurrentUser = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
) -> AppUser:
    return await user_service.update_user(session, user_id, payload)
