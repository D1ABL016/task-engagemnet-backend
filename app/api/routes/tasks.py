import uuid

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.api.deps import CurrentUser, require_any_role, require_manager
from app.database import get_session
from app.models.enums import TaskStatus
from app.models.task import Task
from app.schemas.task import (
    AssignmentRequest,
    DeadlineRequest,
    DeletionRequest,
    ReviewCommentOptional,
    ReviewCommentRequired,
    TaskResponse,
)
from app.services import task_service
from app.services.task_service import TaskAction

router = APIRouter(prefix="/api/v1/tasks", tags=["tasks"])


@router.get("", response_model=list[TaskResponse])
async def list_tasks(
    status_filter: TaskStatus | None = Query(default=None, alias="status"),
    engagement_id: uuid.UUID | None = Query(default=None),
    assignee_id: uuid.UUID | None = Query(default=None),
    deleted: bool = Query(default=False),
    current_user: CurrentUser = Depends(require_any_role),
    session: AsyncSession = Depends(get_session),
) -> list[Task]:
    """Default listing excludes deleted tasks; deleted=true inverts that filter.

    That inversion is the whole cost of the deleted-tasks view — the rows never
    went anywhere.
    """
    query = select(Task).options(selectinload(Task.reviews))
    query = (
        query.where(Task.deleted_at.is_not(None))
        if deleted
        else query.where(Task.deleted_at.is_(None))
    )

    if not current_user.is_manager_or_admin:
        query = query.where(Task.assignee_id == current_user.id)
    if status_filter is not None:
        query = query.where(Task.status == status_filter)
    if engagement_id is not None:
        query = query.where(Task.engagement_id == engagement_id)
    if assignee_id is not None:
        query = query.where(Task.assignee_id == assignee_id)

    result = await session.execute(query.order_by(Task.due_date, Task.sequence))
    return list(result.scalars().all())


@router.get("/{task_id}", response_model=TaskResponse)
async def read_task(
    task_id: uuid.UUID,
    current_user: CurrentUser = Depends(require_any_role),
    session: AsyncSession = Depends(get_session),
) -> Task:
    return await task_service.load_task(
        session,
        task_id,
        actor_id=current_user.id,
        actor_is_manager_or_admin=current_user.is_manager_or_admin,
    )


@router.post("/{task_id}/start", response_model=TaskResponse)
async def start_task(
    task_id: uuid.UUID,
    current_user: CurrentUser = Depends(require_any_role),
    session: AsyncSession = Depends(get_session),
) -> Task:
    return await task_service.transition_task(
        session, task_id, TaskAction.START, current_user.id, current_user.role
    )


@router.post("/{task_id}/submit", response_model=TaskResponse)
async def submit_task(
    task_id: uuid.UUID,
    current_user: CurrentUser = Depends(require_any_role),
    session: AsyncSession = Depends(get_session),
) -> Task:
    return await task_service.transition_task(
        session, task_id, TaskAction.SUBMIT, current_user.id, current_user.role
    )


@router.post("/{task_id}/wait-for-client", response_model=TaskResponse)
async def wait_for_client(
    task_id: uuid.UUID,
    current_user: CurrentUser = Depends(require_any_role),
    session: AsyncSession = Depends(get_session),
) -> Task:
    return await task_service.transition_task(
        session, task_id, TaskAction.WAIT_FOR_CLIENT, current_user.id, current_user.role
    )


@router.post("/{task_id}/resume", response_model=TaskResponse)
async def resume_task(
    task_id: uuid.UUID,
    current_user: CurrentUser = Depends(require_any_role),
    session: AsyncSession = Depends(get_session),
) -> Task:
    """Covers both waiting_for_client and changes_requested.

    From the assignee's point of view it is one intent — pick the task back up —
    so it is one action rather than a route whose name encodes which kind of
    pause it is recovering from.
    """
    return await task_service.transition_task(
        session, task_id, TaskAction.RESUME, current_user.id, current_user.role
    )


@router.post("/{task_id}/approve", response_model=TaskResponse)
async def approve_task(
    task_id: uuid.UUID,
    payload: ReviewCommentOptional = ReviewCommentOptional(),
    current_user: CurrentUser = Depends(require_any_role),
    session: AsyncSession = Depends(get_session),
) -> Task:
    return await task_service.transition_task(
        session,
        task_id,
        TaskAction.APPROVE,
        current_user.id,
        current_user.role,
        payload.comment,
    )


@router.post("/{task_id}/request-changes", response_model=TaskResponse)
async def request_changes(
    task_id: uuid.UUID,
    payload: ReviewCommentRequired,
    current_user: CurrentUser = Depends(require_any_role),
    session: AsyncSession = Depends(get_session),
) -> Task:
    return await task_service.transition_task(
        session,
        task_id,
        TaskAction.REQUEST_CHANGES,
        current_user.id,
        current_user.role,
        payload.comment,
    )


@router.post("/{task_id}/reopen", response_model=TaskResponse)
async def reopen_task(
    task_id: uuid.UUID,
    payload: ReviewCommentRequired,
    current_user: CurrentUser = Depends(require_any_role),
    session: AsyncSession = Depends(get_session),
) -> Task:
    return await task_service.transition_task(
        session,
        task_id,
        TaskAction.REOPEN,
        current_user.id,
        current_user.role,
        payload.comment,
    )


@router.patch("/{task_id}/assignment", response_model=TaskResponse)
async def update_assignment(
    task_id: uuid.UUID,
    payload: AssignmentRequest,
    current_user: CurrentUser = Depends(require_manager),
    session: AsyncSession = Depends(get_session),
) -> Task:
    # exclude_unset distinguishes "field omitted" from an explicit `null" —
    # only fields the client actually sent are passed through, so a PATCH
    # naming just the reviewer leaves the assignee (and status) untouched.
    fields = payload.model_dump(exclude_unset=True)
    return await task_service.update_assignment(
        session, task_id, current_user.id, **fields
    )


@router.patch("/{task_id}/deadline", response_model=TaskResponse)
async def update_deadline(
    task_id: uuid.UUID,
    payload: DeadlineRequest,
    current_user: CurrentUser = Depends(require_manager),
    session: AsyncSession = Depends(get_session),
) -> Task:
    return await task_service.update_deadline(
        session, task_id, payload.due_date, current_user.id
    )


@router.delete("/{task_id}", response_model=TaskResponse)
async def delete_task(
    task_id: uuid.UUID,
    payload: DeletionRequest,
    current_user: CurrentUser = Depends(require_manager),
    session: AsyncSession = Depends(get_session),
) -> Task:
    return await task_service.soft_delete_task(
        session, task_id, payload.reason, current_user.id
    )


@router.post("/{task_id}/restore", response_model=TaskResponse)
async def restore_task(
    task_id: uuid.UUID,
    current_user: CurrentUser = Depends(require_manager),
    session: AsyncSession = Depends(get_session),
) -> Task:
    return await task_service.restore_task(session, task_id, current_user.id)
