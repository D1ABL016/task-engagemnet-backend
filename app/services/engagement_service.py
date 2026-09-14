import uuid
from datetime import datetime, timezone

from sqlalchemy import or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.errors import ConflictError, NotFoundError
from app.core.periods import period_bounds
from app.models.client import Client
from app.models.engagement import Engagement
from app.models.enums import EngagementType, UserRole
from app.models.service_type import ServiceType
from app.models.task import Task
from app.models.user import AppUser
from app.schemas.engagement import EngagementCreate, EngagementUpdate
from app.services.generation_service import generate_tasks_for_engagement

#: Fields this endpoint is not allowed to change, and why. Kept as a mapping
#: so the 409 raised for each names the specific reason rather than a generic
#: "immutable field" message.
_IMMUTABLE_FIELD_REASONS: dict[str, str] = {
    "client_id": "Changing the client would move this engagement under a "
    "different unique-period slot and disown its existing tasks.",
    "service_type_id": "Changing the service type would leave the "
    "engagement's already-generated tasks describing a different service.",
    "period_start": "Changing the period would move this engagement under a "
    "different unique-period slot; create a new engagement for a different "
    "period instead.",
    "engagement_type": "Changing between recurring and one-time after tasks "
    "exist would leave those tasks inconsistent with the engagement's "
    "recurrence.",
}


def visible_tasks(
    engagement: Engagement, actor_id: uuid.UUID, actor_is_manager_or_admin: bool
) -> list[Task]:
    """The tasks of this engagement the actor may see, per the task visibility rule.

    Reused here so a team member reading an engagement cannot see a task's
    assignee/reviewer/detail that they could not see through `GET /tasks/{id}`
    directly — otherwise the task-level visibility rule would be trivially
    bypassed by reading the parent engagement.
    """
    if actor_is_manager_or_admin:
        return list(engagement.tasks)
    return [
        task
        for task in engagement.tasks
        if task.assignee_id == actor_id or task.reviewer_id == actor_id
    ]


async def load_engagement(
    session: AsyncSession,
    engagement_id: uuid.UUID,
    *,
    actor_id: uuid.UUID | None = None,
    actor_is_manager_or_admin: bool = False,
) -> Engagement:
    """Load an engagement, optionally applying the actor's visibility rule.

    `actor_id` is opt-in, the same way `task_service.load_task` is: internal
    callers (creation, generate-next, auto-renew) that are already
    manager-gated at the route pass no actor and get the unfiltered load.
    Only the read route passes one. A team member with no task in this
    engagement gets a 404, not a 403, matching the task-level rule.
    """
    result = await session.execute(
        select(Engagement)
        .options(selectinload(Engagement.tasks))
        .where(Engagement.id == engagement_id, Engagement.deleted_at.is_(None))
        .execution_options(populate_existing=True)
    )
    engagement = result.scalar_one_or_none()
    if engagement is None:
        raise NotFoundError("Engagement not found")
    if actor_id is not None and not actor_is_manager_or_admin:
        if not visible_tasks(engagement, actor_id, actor_is_manager_or_admin):
            raise NotFoundError("Engagement not found")
    return engagement


async def list_engagements(
    session: AsyncSession,
    *,
    actor_id: uuid.UUID,
    actor_is_manager_or_admin: bool,
) -> list[Engagement]:
    """Managers and admins see every engagement; a team member sees only the
    engagements in which they have at least one task, as assignee or reviewer.
    """
    query = (
        select(Engagement)
        .options(selectinload(Engagement.tasks))
        .where(Engagement.deleted_at.is_(None))
    )
    if not actor_is_manager_or_admin:
        query = query.where(
            Engagement.id.in_(
                select(Task.engagement_id).where(
                    or_(
                        Task.assignee_id == actor_id,
                        Task.reviewer_id == actor_id,
                    ),
                    Task.deleted_at.is_(None),
                )
            )
        )
    result = await session.execute(query.order_by(Engagement.start_date.desc()))
    return list(result.scalars().all())


async def _validate_references(
    session: AsyncSession, payload: EngagementCreate, manager_id: uuid.UUID
) -> None:
    client = await session.get(Client, payload.client_id)
    if client is None or client.deleted_at is not None or not client.is_active:
        raise ConflictError("Client does not exist or is inactive")

    service_type = await session.get(ServiceType, payload.service_type_id)
    if service_type is None or service_type.deleted_at is not None or not service_type.is_active:
        raise ConflictError("Service type does not exist or is inactive")

    manager = await session.get(AppUser, manager_id)
    if manager is None or manager.deleted_at is not None or not manager.is_active:
        raise ConflictError("Manager does not exist or is inactive")
    if manager.role not in (UserRole.MANAGER, UserRole.ADMIN):
        raise ConflictError("The nominated manager does not hold a manager role")


async def create_engagement(
    session: AsyncSession,
    payload: EngagementCreate,
    actor_id: uuid.UUID | None,
    actor_role: UserRole,
) -> Engagement:
    """Create an engagement and its tasks in one transaction.

    An engagement never exists without the tasks its service type defines.

    `manager_id` is not taken from the payload as-is: a manager is always
    forced to own what they create (`payload.manager_id`, if sent, is
    ignored), since letting a manager name someone else as owner would let
    them hand off accountability for an engagement they never intend to
    manage. Only an admin, who owns nothing themselves by default, must name
    one explicitly.
    """
    if actor_role is UserRole.MANAGER:
        manager_id = actor_id
    else:
        if payload.manager_id is None:
            raise ConflictError("manager_id is required")
        manager_id = payload.manager_id

    await _validate_references(session, payload, manager_id)

    if payload.engagement_type is EngagementType.RECURRING:
        period_start, period_end = period_bounds(payload.recurrence, payload.start_date)
        anchor_date = period_start
    else:
        period_start, period_end, anchor_date = None, None, payload.start_date

    engagement = Engagement(
        client_id=payload.client_id,
        service_type_id=payload.service_type_id,
        manager_id=manager_id,
        engagement_type=payload.engagement_type,
        recurrence=payload.recurrence,
        start_date=anchor_date,
        period_start=period_start,
        period_end=period_end,
        auto_renew=True,
        updated_by=actor_id,
    )
    session.add(engagement)

    try:
        await session.flush()
        await generate_tasks_for_engagement(session, engagement)
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        if "engagement_unique_period" in str(exc.orig):
            raise ConflictError(
                "An engagement already exists for this client, service and period"
            ) from exc
        raise

    return await load_engagement(session, engagement.id)


async def update_engagement(
    session: AsyncSession,
    engagement_id: uuid.UUID,
    payload: EngagementUpdate,
    actor_id: uuid.UUID,
) -> Engagement:
    """Change `manager_id` and/or `auto_renew`; reject anything else.

    `client_id`, `service_type_id`, `period_start` and `engagement_type` are
    on the payload only so a genuine attempt to change one can be told apart
    from the client simply resubmitting the value it already read — the
    latter is a no-op, the former is rejected with a 409 naming why.

    Changing `manager_id` does NOT retroactively change `reviewer_id` on this
    engagement's existing tasks. Those were set to the manager at the time
    each task was generated and are copies, exactly like a task's title — a
    new manager reviews only tasks generated from now on (ad-hoc tasks
    created after this call, or a future period's tasks) unless someone also
    restaffs the existing ones via `PATCH /tasks/{id}/assignment`.
    """
    engagement = await load_engagement(session, engagement_id)
    updates = payload.model_dump(exclude_unset=True)

    for field_name, reason in _IMMUTABLE_FIELD_REASONS.items():
        if field_name in updates and updates[field_name] != getattr(engagement, field_name):
            raise ConflictError(
                f"Cannot change '{field_name}' on an existing engagement. {reason}"
            )

    if "manager_id" in updates:
        if updates["manager_id"] is None:
            raise ConflictError("manager_id cannot be cleared; an engagement always has a manager")
        manager = await session.get(AppUser, updates["manager_id"])
        if manager is None or manager.deleted_at is not None or not manager.is_active:
            raise ConflictError("Manager does not exist or is inactive")
        if manager.role not in (UserRole.MANAGER, UserRole.ADMIN):
            raise ConflictError("The nominated manager does not hold a manager role")
        engagement.manager_id = manager.id

    if "auto_renew" in updates:
        if updates["auto_renew"] is None:
            raise ConflictError("auto_renew cannot be cleared")
        engagement.auto_renew = updates["auto_renew"]

    engagement.updated_by = actor_id
    await session.commit()
    return await load_engagement(session, engagement_id)


async def set_auto_renew(
    session: AsyncSession,
    engagement_id: uuid.UUID,
    enabled: bool,
    actor_id: uuid.UUID,
) -> Engagement:
    """Turning this off ends the series after the current period.

    Kept distinct from soft delete: deleting means "this should not have
    existed", ending a recurrence means "this was correct, and now we stop".
    """
    engagement = await load_engagement(session, engagement_id)
    engagement.auto_renew = enabled
    engagement.updated_by = actor_id
    await session.commit()
    return await load_engagement(session, engagement_id)


async def soft_delete_engagement(
    session: AsyncSession,
    engagement_id: uuid.UUID,
    reason: str,
    actor_id: uuid.UUID,
) -> Engagement:
    """Soft-delete the engagement and cascade the delete to its tasks.

    This is an UPDATE, not a DELETE, so `deleted_by` records the actor doing
    the deleting rather than whoever last touched the row (which is all a
    hard-delete audit trigger would have to go on).

    Cascade choice: an engagement that vanishes while its tasks stay live on
    dashboards and task listings is incoherent, so every non-deleted task of
    this engagement is soft-deleted in the SAME transaction, with the reason
    prefixed `"Engagement deleted: <reason>"` so the cascade is visible in
    the task's own audit trail.

    Discriminating cascade-deleted tasks from tasks deleted individually
    beforehand: a cascade-deleted task's `deleted_at` is set to exactly the
    engagement's `deleted_at` (the same timestamp value, computed once and
    reused for both). A task deleted individually before this call already
    has an earlier `deleted_at` and is left untouched — both by this delete
    and by the matching restore. Restore then reverses precisely the tasks
    whose `deleted_at == engagement.deleted_at`.
    """
    engagement = await load_engagement(session, engagement_id)
    deleted_at = datetime.now(timezone.utc)

    engagement.deleted_at = deleted_at
    engagement.deleted_by = actor_id
    engagement.deletion_reason = reason
    engagement.updated_by = actor_id

    result = await session.execute(
        select(Task).where(Task.engagement_id == engagement_id, Task.deleted_at.is_(None))
    )
    for task in result.scalars().all():
        task.deleted_at = deleted_at
        task.deleted_by = actor_id
        task.deletion_reason = f"Engagement deleted: {reason}"
        task.updated_by = actor_id

    await session.commit()
    return await load_engagement_including_deleted(session, engagement_id)


async def restore_engagement(
    session: AsyncSession, engagement_id: uuid.UUID, actor_id: uuid.UUID
) -> Engagement:
    """Reverse a soft delete, and only the tasks this cascade deleted.

    A restore can legitimately fail: if another engagement now occupies this
    client/service/period, `engagement_unique_period` rejects the UPDATE. That
    IntegrityError is caught and turned into a clear 409 rather than a 500.
    """
    engagement = await load_engagement_including_deleted(session, engagement_id)
    if engagement.deleted_at is None:
        raise ConflictError("This engagement is not deleted")

    cascade_marker = engagement.deleted_at

    engagement.deleted_at = None
    engagement.deleted_by = None
    engagement.deletion_reason = None
    engagement.updated_by = actor_id

    try:
        await session.flush()
    except IntegrityError as exc:
        await session.rollback()
        if "engagement_unique_period" in str(exc.orig):
            raise ConflictError(
                "Cannot restore: another engagement now occupies this "
                "client, service and period"
            ) from exc
        raise

    result = await session.execute(
        select(Task).where(
            Task.engagement_id == engagement_id, Task.deleted_at == cascade_marker
        )
    )
    for task in result.scalars().all():
        task.deleted_at = None
        task.deleted_by = None
        task.deletion_reason = None
        task.updated_by = actor_id

    await session.commit()
    return await load_engagement(session, engagement_id)


async def load_engagement_including_deleted(
    session: AsyncSession, engagement_id: uuid.UUID
) -> Engagement:
    """Like `load_engagement`, but visible even after a soft delete.

    Needed by delete/restore, which must operate on the row they just
    (un)deleted.
    """
    result = await session.execute(
        select(Engagement)
        .options(selectinload(Engagement.tasks))
        .where(Engagement.id == engagement_id)
        .execution_options(populate_existing=True)
    )
    engagement = result.scalar_one_or_none()
    if engagement is None:
        raise NotFoundError("Engagement not found")
    return engagement
