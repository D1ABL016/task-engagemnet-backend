import uuid

from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import CurrentUser, require_admin, require_any_role
from app.database import get_session
from app.models.service_type import ServiceType, TaskTemplate
from app.schemas.service_type import (
    ServiceTypeCreate,
    ServiceTypeResponse,
    ServiceTypeUpdate,
    TaskTemplateCreate,
    TaskTemplateResponse,
    TaskTemplateUpdate,
)
from app.services import service_type_service

router = APIRouter(prefix="/api/v1", tags=["service types"])


@router.get("/service-types", response_model=list[ServiceTypeResponse])
async def list_service_types(
    _: CurrentUser = Depends(require_any_role),
    session: AsyncSession = Depends(get_session),
) -> list[ServiceType]:
    return await service_type_service.list_service_types(session)


@router.post(
    "/service-types", response_model=ServiceTypeResponse, status_code=status.HTTP_201_CREATED
)
async def create_service_type(
    payload: ServiceTypeCreate,
    current_user: CurrentUser = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
) -> ServiceType:
    return await service_type_service.create_service_type(session, payload, current_user.id)


@router.patch("/service-types/{service_type_id}", response_model=ServiceTypeResponse)
async def update_service_type(
    service_type_id: uuid.UUID,
    payload: ServiceTypeUpdate,
    current_user: CurrentUser = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
) -> ServiceType:
    return await service_type_service.update_service_type(
        session, service_type_id, payload, current_user.id
    )


@router.post(
    "/service-types/{service_type_id}/templates",
    response_model=TaskTemplateResponse,
    status_code=status.HTTP_201_CREATED,
)
async def add_task_template(
    service_type_id: uuid.UUID,
    payload: TaskTemplateCreate,
    current_user: CurrentUser = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
) -> TaskTemplate:
    return await service_type_service.add_task_template(
        session, service_type_id, payload, current_user.id
    )


@router.patch("/task-templates/{template_id}", response_model=TaskTemplateResponse)
async def update_task_template(
    template_id: uuid.UUID,
    payload: TaskTemplateUpdate,
    current_user: CurrentUser = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
) -> TaskTemplate:
    return await service_type_service.update_task_template(
        session, template_id, payload, current_user.id
    )


@router.delete("/task-templates/{template_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_task_template(
    template_id: uuid.UUID,
    current_user: CurrentUser = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
) -> None:
    await service_type_service.delete_task_template(session, template_id)
