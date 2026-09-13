import uuid

from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import CurrentUser, require_any_role, require_manager
from app.core.errors import ConflictError
from app.database import get_session
from app.models.engagement import Engagement
from app.models.enums import EngagementType
from app.models.task import Task
from app.schemas.engagement import (
    AutoRenewRequest,
    EngagementCreate,
    EngagementResponse,
    EngagementUpdate,
    GenerateNextResponse,
    TaskSummary,
)
from app.schemas.task import AdHocTaskCreate, DeletionRequest, TaskResponse
from app.services import engagement_service, task_service
from app.services.generation_service import create_next_period

router = APIRouter(prefix="/api/v1/engagements", tags=["engagements"])


def _to_response(engagement: Engagement, current_user: CurrentUser) -> EngagementResponse:
    """Build the response, embedding only the tasks this actor may see.

    Otherwise a team member could see another person's task detail (assignee,
    reviewer, status) by reading the parent engagement even though
    `GET /tasks/{id}` would 404 them on the same task directly.
    """
    response = EngagementResponse.model_validate(engagement)
    response.tasks = [
        TaskSummary.model_validate(task)
        for task in engagement_service.visible_tasks(
            engagement, current_user.id, current_user.is_manager_or_admin
        )
    ]
    return response


@router.post("", response_model=EngagementResponse, status_code=status.HTTP_201_CREATED)
async def create_engagement(
    payload: EngagementCreate,
    current_user: CurrentUser = Depends(require_manager),
    session: AsyncSession = Depends(get_session),
) -> Engagement:
    return await engagement_service.create_engagement(session, payload, current_user.id)


@router.get("", response_model=list[EngagementResponse])
async def list_engagements(
    current_user: CurrentUser = Depends(require_any_role),
    session: AsyncSession = Depends(get_session),
) -> list[EngagementResponse]:
    """Managers/admins see every engagement; a team member sees only the
    engagements they have a task in, each with only their own tasks embedded.
    """
    engagements = await engagement_service.list_engagements(
        session,
        actor_id=current_user.id,
        actor_is_manager_or_admin=current_user.is_manager_or_admin,
    )
    return [_to_response(engagement, current_user) for engagement in engagements]


@router.get("/{engagement_id}", response_model=EngagementResponse)
async def read_engagement(
    engagement_id: uuid.UUID,
    current_user: CurrentUser = Depends(require_any_role),
    session: AsyncSession = Depends(get_session),
) -> EngagementResponse:
    engagement = await engagement_service.load_engagement(
        session,
        engagement_id,
        actor_id=current_user.id,
        actor_is_manager_or_admin=current_user.is_manager_or_admin,
    )
    return _to_response(engagement, current_user)


@router.patch("/{engagement_id}", response_model=EngagementResponse)
async def update_engagement(
    engagement_id: uuid.UUID,
    payload: EngagementUpdate,
    current_user: CurrentUser = Depends(require_manager),
    session: AsyncSession = Depends(get_session),
) -> EngagementResponse:
    """Change `manager_id` and/or `auto_renew` only.

    Changing `manager_id` does not retroactively change `reviewer_id` on this
    engagement's existing tasks — see `engagement_service.update_engagement`.
    """
    engagement = await engagement_service.update_engagement(
        session, engagement_id, payload, current_user.id
    )
    return _to_response(engagement, current_user)


@router.delete("/{engagement_id}", response_model=EngagementResponse)
async def delete_engagement(
    engagement_id: uuid.UUID,
    payload: DeletionRequest,
    current_user: CurrentUser = Depends(require_manager),
    session: AsyncSession = Depends(get_session),
) -> EngagementResponse:
    """Soft-delete the engagement and cascade the delete to its live tasks.

    See `engagement_service.soft_delete_engagement` for the cascade rule and
    how a restore tells cascade-deleted tasks apart from tasks that were
    already deleted individually.
    """
    engagement = await engagement_service.soft_delete_engagement(
        session, engagement_id, payload.reason, current_user.id
    )
    return _to_response(engagement, current_user)


@router.post("/{engagement_id}/restore", response_model=EngagementResponse)
async def restore_engagement(
    engagement_id: uuid.UUID,
    current_user: CurrentUser = Depends(require_manager),
    session: AsyncSession = Depends(get_session),
) -> EngagementResponse:
    """Reverse a soft delete, including the tasks that delete cascaded to.

    Fails with 409, not 500, if another engagement now occupies this
    client/service/period slot.
    """
    engagement = await engagement_service.restore_engagement(
        session, engagement_id, current_user.id
    )
    return _to_response(engagement, current_user)


@router.post("/{engagement_id}/generate-next", response_model=GenerateNextResponse)
async def generate_next_period(
    engagement_id: uuid.UUID,
    current_user: CurrentUser = Depends(require_manager),
    session: AsyncSession = Depends(get_session),
) -> GenerateNextResponse:
    """Calls the same service function as the scheduled job.

    The demo path and the automated path cannot drift apart, and a manager
    pressing this repeatedly is exactly as safe as the job double-firing.
    """
    engagement = await engagement_service.load_engagement(session, engagement_id)
    if engagement.engagement_type is not EngagementType.RECURRING:
        raise ConflictError("Only recurring engagements have a next period")

    created, next_engagement = await create_next_period(
        session, engagement, actor_id=current_user.id
    )
    loaded = await engagement_service.load_engagement(session, next_engagement.id)
    return GenerateNextResponse(created=created, engagement=loaded)


@router.patch("/{engagement_id}/auto-renew", response_model=EngagementResponse)
async def set_auto_renew(
    engagement_id: uuid.UUID,
    payload: AutoRenewRequest,
    current_user: CurrentUser = Depends(require_manager),
    session: AsyncSession = Depends(get_session),
) -> Engagement:
    return await engagement_service.set_auto_renew(
        session, engagement_id, payload.enabled, current_user.id
    )


@router.post(
    "/{engagement_id}/tasks", response_model=TaskResponse, status_code=status.HTTP_201_CREATED
)
async def add_adhoc_task(
    engagement_id: uuid.UUID,
    payload: AdHocTaskCreate,
    current_user: CurrentUser = Depends(require_manager),
    session: AsyncSession = Depends(get_session),
) -> Task:
    return await task_service.create_adhoc_task(
        session,
        engagement_id,
        payload.title,
        payload.due_date,
        payload.assignee_id,
        current_user.id,
    )
