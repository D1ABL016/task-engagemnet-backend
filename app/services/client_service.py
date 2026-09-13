import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import NotFoundError
from app.models.client import Client
from app.schemas.client import ClientCreate, ClientUpdate


async def load_client(session: AsyncSession, client_id: uuid.UUID) -> Client:
    result = await session.execute(
        select(Client).where(Client.id == client_id, Client.deleted_at.is_(None))
    )
    client = result.scalar_one_or_none()
    if client is None:
        raise NotFoundError("Client not found")
    return client


async def list_clients(session: AsyncSession) -> list[Client]:
    result = await session.execute(
        select(Client).where(Client.deleted_at.is_(None)).order_by(Client.name)
    )
    return list(result.scalars().all())


async def create_client(
    session: AsyncSession, payload: ClientCreate, actor_id: uuid.UUID
) -> Client:
    client = Client(
        name=payload.name,
        contact_email=payload.contact_email,
        is_active=True,
        updated_by=actor_id,
    )
    session.add(client)
    await session.commit()
    await session.refresh(client)
    return client


async def update_client(
    session: AsyncSession,
    client_id: uuid.UUID,
    payload: ClientUpdate,
    actor_id: uuid.UUID,
) -> Client:
    client = await load_client(session, client_id)

    for field_name, value in payload.model_dump(exclude_unset=True).items():
        setattr(client, field_name, value)
    client.updated_by = actor_id
    await session.commit()
    await session.refresh(client)
    return client
