import uuid

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.errors import ConflictError, NotFoundError
from app.models.service_type import ServiceType, TaskTemplate
from app.models.task import Task
from app.schemas.service_type import (
    ServiceTypeCreate,
    ServiceTypeUpdate,
    TaskTemplateCreate,
    TaskTemplateUpdate,
)


async def load_service_type(
    session: AsyncSession, service_type_id: uuid.UUID
) -> ServiceType:
    result = await session.execute(
        select(ServiceType)
        .options(selectinload(ServiceType.task_templates))
        .where(ServiceType.id == service_type_id, ServiceType.deleted_at.is_(None))
    )
    service_type = result.scalar_one_or_none()
    if service_type is None:
        raise NotFoundError("Service type not found")
    return service_type


async def list_service_types(session: AsyncSession) -> list[ServiceType]:
    result = await session.execute(
        select(ServiceType)
        .options(selectinload(ServiceType.task_templates))
        .where(ServiceType.deleted_at.is_(None))
        .order_by(ServiceType.name)
    )
    return list(result.scalars().all())


async def create_service_type(
    session: AsyncSession, payload: ServiceTypeCreate, actor_id: uuid.UUID
) -> ServiceType:
    service_type = ServiceType(
        name=payload.name,
        description=payload.description,
        is_active=True,
        updated_by=actor_id,
    )
    session.add(service_type)
    try:
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        if "service_type_name_key" in str(exc.orig):
            raise ConflictError("A service type with that name already exists") from exc
        raise
    return await load_service_type(session, service_type.id)


async def update_service_type(
    session: AsyncSession,
    service_type_id: uuid.UUID,
    payload: ServiceTypeUpdate,
    actor_id: uuid.UUID,
) -> ServiceType:
    """Rename, redescribe or (de)activate a service type.

    `is_active` does not touch existing engagements or tasks; it only stops
    new engagements from being created against this service type.
    """
    service_type = await load_service_type(session, service_type_id)

    for field_name, value in payload.model_dump(exclude_unset=True).items():
        setattr(service_type, field_name, value)
    service_type.updated_by = actor_id

    try:
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        if "service_type_name_key" in str(exc.orig):
            raise ConflictError("A service type with that name already exists") from exc
        raise
    return await load_service_type(session, service_type_id)


async def add_task_template(
    session: AsyncSession,
    service_type_id: uuid.UUID,
    payload: TaskTemplateCreate,
    actor_id: uuid.UUID,
) -> TaskTemplate:
    await load_service_type(session, service_type_id)

    template = TaskTemplate(
        service_type_id=service_type_id,
        title=payload.title,
        sequence=payload.sequence,
        default_offset_days=payload.default_offset_days,
        updated_by=actor_id,
    )
    session.add(template)
    try:
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        if "task_template_sequence_unique" in str(exc.orig):
            raise ConflictError(
                f"Sequence {payload.sequence} is already used by another template "
                "for this service type"
            ) from exc
        raise
    await session.refresh(template)
    return template


async def load_task_template(session: AsyncSession, template_id: uuid.UUID) -> TaskTemplate:
    result = await session.execute(
        select(TaskTemplate).where(TaskTemplate.id == template_id)
    )
    template = result.scalar_one_or_none()
    if template is None:
        raise NotFoundError("Task template not found")
    return template


async def update_task_template(
    session: AsyncSession,
    template_id: uuid.UUID,
    payload: TaskTemplateUpdate,
    actor_id: uuid.UUID,
) -> TaskTemplate:
    """Editing a template never changes tasks that already exist.

    Tasks copy title, sequence and the resolved due date at generation time, so
    a correction here affects only periods generated from now on.
    """
    template = await load_task_template(session, template_id)

    for field_name, value in payload.model_dump(exclude_unset=True).items():
        setattr(template, field_name, value)
    template.updated_by = actor_id
    await session.commit()
    await session.refresh(template)
    return template


async def delete_task_template(session: AsyncSession, template_id: uuid.UUID) -> None:
    """Hard delete: `task_template` has no soft-delete columns.

    Existing tasks reference the template via `task_template_id` for
    provenance only — title, sequence and due date were copied onto the task
    at generation time and are never read through the template. So deleting
    a template nulls out `task_template_id` on every task that referenced it,
    in the same transaction, rather than being blocked by the foreign key.
    Those tasks become indistinguishable from ad-hoc tasks, which is correct:
    their template no longer exists, and their own title, sequence and due
    date are untouched.
    """
    template = await load_task_template(session, template_id)

    await session.execute(
        Task.__table__.update()
        .where(Task.task_template_id == template_id)
        .values(task_template_id=None)
    )
    await session.delete(template)
    await session.commit()
