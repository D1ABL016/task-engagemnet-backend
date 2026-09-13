import uuid
from datetime import date

from sqlalchemy import Select, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.engagement import Engagement
from app.models.enums import TaskStatus
from app.models.task import Task
from app.schemas.dashboard import DashboardSummary

#: Every status except the terminal one.
OPEN_STATUSES = [status for status in TaskStatus if status is not TaskStatus.COMPLETED]


def _visible_tasks_query(actor_id: uuid.UUID, actor_is_manager_or_admin: bool) -> Select:
    """Team members see only their own tasks; managers and admins see everything.

    Applied to every dashboard count, so a team member's numbers describe their
    own workload rather than the firm's.
    """
    query = select(Task).where(Task.deleted_at.is_(None))
    if not actor_is_manager_or_admin:
        query = query.where(Task.assignee_id == actor_id)
    return query


def _current_period_only(query: Select, today: date) -> Select:
    """Exclude engagements whose period has not begun.

    The recurrence job creates the next period a few days early so the team can
    staff it. Counting those as open work would make every month-end look like a
    sudden jump in workload for work nobody is meant to have started.

    A one-time engagement has a NULL period_start and is always current.
    """
    return query.join(Engagement, Engagement.id == Task.engagement_id).where(
        (Engagement.period_start.is_(None)) | (Engagement.period_start <= today)
    )


async def _count(session: AsyncSession, query: Select) -> int:
    result = await session.execute(
        select(func.count()).select_from(query.subquery())
    )
    return int(result.scalar_one())


async def build_dashboard(
    session: AsyncSession,
    actor_id: uuid.UUID,
    actor_is_manager_or_admin: bool,
    today: date | None = None,
) -> DashboardSummary:
    today = today or date.today()
    base = _visible_tasks_query(actor_id, actor_is_manager_or_admin)
    current = _current_period_only(base, today)

    open_tasks = current.where(Task.status.in_(OPEN_STATUSES))

    upcoming_query = (
        base.join(Engagement, Engagement.id == Task.engagement_id)
        .where(Engagement.period_start.is_not(None), Engagement.period_start > today)
        .where(Task.status.in_(OPEN_STATUSES))
    )

    deleted_query = select(Task).where(Task.deleted_at.is_not(None))
    if not actor_is_manager_or_admin:
        deleted_query = deleted_query.where(Task.assignee_id == actor_id)

    return DashboardSummary(
        unassigned=await _count(session, current.where(Task.status == TaskStatus.NOT_STARTED)),
        open_tasks=await _count(session, open_tasks),
        due_today=await _count(session, open_tasks.where(Task.due_date == today)),
        overdue=await _count(session, open_tasks.where(Task.due_date < today)),
        waiting_for_client=await _count(
            session, current.where(Task.status == TaskStatus.WAITING_FOR_CLIENT)
        ),
        waiting_for_review=await _count(
            session, current.where(Task.status == TaskStatus.READY_FOR_REVIEW)
        ),
        needs_rework=await _count(
            session, current.where(Task.status == TaskStatus.CHANGES_REQUESTED)
        ),
        upcoming=await _count(session, upcoming_query),
        deleted=await _count(session, deleted_query),
    )
