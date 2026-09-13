import uuid

from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import CurrentUser, require_admin, require_any_role
from app.database import get_session
from app.models.client import Client
from app.schemas.client import ClientCreate, ClientResponse, ClientUpdate
from app.services import client_service

router = APIRouter(prefix="/api/v1/clients", tags=["clients"])


@router.get("", response_model=list[ClientResponse])
async def list_clients(
    _: CurrentUser = Depends(require_any_role),
    session: AsyncSession = Depends(get_session),
) -> list[Client]:
    return await client_service.list_clients(session)


@router.post("", response_model=ClientResponse, status_code=status.HTTP_201_CREATED)
async def create_client(
    payload: ClientCreate,
    current_user: CurrentUser = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
) -> Client:
    return await client_service.create_client(session, payload, current_user.id)


@router.patch("/{client_id}", response_model=ClientResponse)
async def update_client(
    client_id: uuid.UUID,
    payload: ClientUpdate,
    current_user: CurrentUser = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
) -> Client:
    return await client_service.update_client(session, client_id, payload, current_user.id)
