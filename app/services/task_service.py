import enum
import uuid
from datetime import date, datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.errors import ConflictError, NotFoundError, PermissionDeniedError
from app.models.engagement import Engagement
from app.models.enums import ReviewDecision, TaskStatus, UserRole
from app.models.task import Task, TaskReview
from app.models.user import AppUser

#: Statuses from which clearing the assignee is still meaningful.
UNSTAFFED_STATUSES = {TaskStatus.NOT_STARTED, TaskStatus.ASSIGNED}

#: Sentinel distinguishing "field omitted from the request" from an explicit
#: `null`. Used by `update_assignment` so a PATCH that only names one field
#: does not clobber the other.
_UNSET = object()


class TaskAction(str, enum.Enum):
    START = "start"
    SUBMIT = "submit"
    WAIT_FOR_CLIENT = "wait-for-client"
    RESUME = "resume"
    APPROVE = "approve"
    REQUEST_CHANGES = "request-changes"
    REOPEN = "reopen"


#: The single source of truth. Anything absent from this mapping is rejected.
#: Note what is deliberately missing: not_started -> in_progress (nobody can
#: start work on a task with no owner), assigned -> ready_for_review (no
#: submitting work never started), waiting_for_client -> ready_for_review
#: (unblock first), and any path out of completed except the explicit reopen.
TRANSITIONS: dict[tuple[TaskStatus, TaskAction], TaskStatus] = {
    (TaskStatus.ASSIGNED, TaskAction.START): TaskStatus.IN_PROGRESS,
    (TaskStatus.IN_PROGRESS, TaskAction.WAIT_FOR_CLIENT): TaskStatus.WAITING_FOR_CLIENT,
    (TaskStatus.WAITING_FOR_CLIENT, TaskAction.RESUME): TaskStatus.IN_PROGRESS,
    (TaskStatus.IN_PROGRESS, TaskAction.SUBMIT): TaskStatus.READY_FOR_REVIEW,
    (TaskStatus.READY_FOR_REVIEW, TaskAction.APPROVE): TaskStatus.COMPLETED,
    (TaskStatus.READY_FOR_REVIEW, TaskAction.REQUEST_CHANGES): TaskStatus.CHANGES_REQUESTED,
    (TaskStatus.CHANGES_REQUESTED, TaskAction.RESUME): TaskStatus.IN_PROGRESS,
    (TaskStatus.COMPLETED, TaskAction.REOPEN): TaskStatus.IN_PROGRESS,
}

#: Actions the reviewer performs. Everything else is the assignee's.
REVIEW_ACTIONS = {TaskAction.APPROVE, TaskAction.REQUEST_CHANGES, TaskAction.REOPEN}

REVIEW_DECISIONS: dict[TaskAction, ReviewDecision] = {
    TaskAction.APPROVE: ReviewDecision.APPROVED,
    TaskAction.REQUEST_CHANGES: ReviewDecision.CHANGES_REQUESTED,
    TaskAction.REOPEN: ReviewDecision.REOPENED,
}


def _check_actor_may_act(
    task: Task, action: TaskAction, actor_id: uuid.UUID, actor_role: UserRole
) -> None:
    """Relational authorization: not "is a manager" but "is THIS task's reviewer".

    This cannot live in a route dependency, because it needs the row. The route
    dependency does the coarse role filter; this does the fine relational one.
    """
    is_admin = actor_role is UserRole.ADMIN
    if action in REVIEW_ACTIONS:
        is_named_reviewer = task.reviewer_id == actor_id
        if not (is_named_reviewer or is_admin):
            raise PermissionDeniedError(
                "Only this task's reviewer or an admin may review it"
            )
        return

    is_manager_or_admin = actor_role in (UserRole.MANAGER, UserRole.ADMIN)
    is_assignee = task.assignee_id == actor_id
    if not (is_assignee or is_manager_or_admin):
        raise PermissionDeniedError("Only the assignee or a manager may update this task")


def visibility_clause(actor_id: uuid.UUID, actor_role: UserRole):
    """The WHERE clause restricting tasks to what this role may see.

    Per-role, not just "manager or admin vs. everyone else": a team member
    sees only tasks assigned to them, a manager sees only tasks where they are
    the named reviewer, and an admin sees everything (clause is None). This is
    the single source of truth for that split — `list_tasks`, `load_task`, and
    `task_is_visible_to` all defer to it so the three stay in lockstep.
    """
    if actor_role is UserRole.ADMIN:
        return None
    if actor_role is UserRole.MANAGER:
        return Task.reviewer_id == actor_id
    return Task.assignee_id == actor_id


def _require_reviewer_or_admin(
    task: Task, actor_id: uuid.UUID, actor_role: UserRole
) -> None:
    """Relational gate for the staffing/deadline/delete/restore PATCH routes.

    Those routes are already role-gated to manager/admin at the dependency
    level, but that alone would let any manager touch any task. A manager may
    only modify a task they are the named reviewer of; an admin may modify
    any task. A manager who is not this task's reviewer gets a 404, matching
    the read-side visibility rule, so the response does not itself confirm
    the task exists.
    """
    if actor_role is UserRole.MANAGER and task.reviewer_id != actor_id:
        raise NotFoundError("Task not found")


async def load_task(
    session: AsyncSession,
    task_id: uuid.UUID,
    *,
    include_deleted: bool = False,
    actor_id: uuid.UUID | None = None,
    actor_role: UserRole | None = None,
) -> Task:
    """Load a task, optionally applying the actor's visibility rule.

    `actor_id` is opt-in: internal callers that already own the task (a
    workflow transition reloading after its own write, a soft-delete/restore
    round trip) pass no actor and get the unfiltered load they always have.
    Only the read route passes an actor, which is what makes the visibility
    rule apply there without changing every other caller's behaviour.

    When an actor is given, `visibility_clause` decides what they may see: a
    team member only their own assigned tasks, a manager only tasks they
    review, an admin everything. Anyone excluded gets a 404 (not 403), since
    a 403 would itself confirm the task exists.
    """
    query = select(Task).options(selectinload(Task.reviews)).where(Task.id == task_id)
    if not include_deleted:
        query = query.where(Task.deleted_at.is_(None))
    if actor_id is not None and actor_role is not None:
        clause = visibility_clause(actor_id, actor_role)
        if clause is not None:
            query = query.where(clause)
    result = await session.execute(query)
    task = result.scalar_one_or_none()
    if task is None:
        raise NotFoundError("Task not found")
    return task


def task_is_visible_to(task: Task, actor_id: uuid.UUID, actor_role: UserRole) -> bool:
    """The same visibility predicate as `load_task`, for filtering collections.

    Used to strip tasks a team member (or a manager who is not the reviewer)
    may not see out of an embedded list (an engagement's `tasks[]`), so the
    task-level rule cannot be bypassed by reading the parent resource instead
    of the task directly.
    """
    if actor_role is UserRole.ADMIN:
        return True
    if actor_role is UserRole.MANAGER:
        return task.reviewer_id == actor_id
    return task.assignee_id == actor_id


async def _require_active_user(
    session: AsyncSession, user_id: uuid.UUID, label: str
) -> AppUser:
    user = await session.get(AppUser, user_id)
    if user is None or user.deleted_at is not None or not user.is_active:
        raise ConflictError(f"{label} does not exist or is inactive")
    return user


async def transition_task(
    session: AsyncSession,
    task_id: uuid.UUID,
    action: TaskAction,
    actor_id: uuid.UUID,
    actor_role: UserRole,
    comment: str | None = None,
) -> Task:
    """Every workflow state change in the system goes through here.

    The task row is locked FOR UPDATE before the transition is checked, because
    checking the current status and writing the new one is otherwise a
    check-then-write with a gap: two concurrent requests could both read
    ready_for_review, both pass the check, and both write, producing two
    task_review rows for one approval. The realistic case is a reviewer
    double-clicking or acting from two tabs.
    """
    locked = await session.execute(
        select(Task).where(Task.id == task_id).with_for_update()
    )
    task = locked.scalar_one_or_none()
    if task is None:
        raise NotFoundError("Task not found")

    if task.deleted_at is not None:
        raise ConflictError("This task is deleted. Restore it before working on it.")

    target_status = TRANSITIONS.get((task.status, action))
    if target_status is None:
        raise ConflictError(
            f"Cannot {action.value} a task that is {task.status.value}"
        )

    _check_actor_may_act(task, action, actor_id, actor_role)

    if action is TaskAction.APPROVE and task.assignee_id == actor_id:
        raise ConflictError("You cannot approve your own work")

    task.status = target_status
    task.updated_by = actor_id

    if action in REVIEW_ACTIONS:
        session.add(
            TaskReview(
                task_id=task.id,
                reviewer_id=actor_id,
                decision=REVIEW_DECISIONS[action],
                comment=comment,
            )
        )

    await session.commit()
    return await load_task(session, task_id)


async def update_assignment(
    session: AsyncSession,
    task_id: uuid.UUID,
    actor_id: uuid.UUID,
    actor_role: UserRole,
    assignee_id: uuid.UUID | None = _UNSET,
    reviewer_id: uuid.UUID | None = _UNSET,
) -> Task:
    """Staffing a task, which moves its status as a consequence.

    `assignee_id` and `reviewer_id` default to a sentinel meaning "the request
    did not mention this field" — distinct from an explicit `null`, which means
    "clear it" (assignee only; a reviewer can never be null, the column is
    NOT NULL). The caller passes `**payload.model_dump(exclude_unset=True))`,
    so a PATCH naming only one field leaves the other exactly as it was.

    Assignment is not a workflow action because the status change follows from
    staffing rather than being a thing a user asks for directly:

      - setting an assignee on a not_started task moves it to assigned
      - clearing it on an assigned task moves it back to not_started
      - changing it on a task already in progress leaves the status alone,
        because reassigning mid-flight must not rewind real progress
      - clearing it past assigned is refused: use the workflow first
    """
    locked = await session.execute(
        select(Task).where(Task.id == task_id).with_for_update()
    )
    task = locked.scalar_one_or_none()
    if task is None:
        raise NotFoundError("Task not found")
    if task.deleted_at is not None:
        raise ConflictError("This task is deleted. Restore it first.")
    _require_reviewer_or_admin(task, actor_id, actor_role)

    if reviewer_id is not _UNSET:
        if actor_role is not UserRole.ADMIN:
            raise PermissionDeniedError("Only an admin may change a task's reviewer")
        if reviewer_id is None:
            raise ConflictError("A task must always have a reviewer")
        await _require_active_user(session, reviewer_id, "Reviewer")
        task.reviewer_id = reviewer_id

    if assignee_id is not _UNSET:
        if assignee_id is None and task.status not in UNSTAFFED_STATUSES:
            raise ConflictError(
                f"Cannot unassign a task that is {task.status.value}. "
                "Move it back through the workflow first."
            )
        if assignee_id is not None:
            await _require_active_user(session, assignee_id, "Assignee")

        task.assignee_id = assignee_id

        if assignee_id is not None and task.status is TaskStatus.NOT_STARTED:
            task.status = TaskStatus.ASSIGNED
        elif assignee_id is None and task.status is TaskStatus.ASSIGNED:
            task.status = TaskStatus.NOT_STARTED

    if task.assignee_id is not None and task.assignee_id == task.reviewer_id:
        raise ConflictError(
            "The assignee and the reviewer cannot be the same person, because "
            "nobody may approve their own work"
        )

    task.updated_by = actor_id
    await session.commit()
    return await load_task(session, task_id)


async def update_deadline(
    session: AsyncSession,
    task_id: uuid.UUID,
    due_date: date | None,
    actor_id: uuid.UUID,
    actor_role: UserRole,
) -> Task:
    task = await load_task(session, task_id)
    _require_reviewer_or_admin(task, actor_id, actor_role)
    task.due_date = due_date
    task.updated_by = actor_id
    await session.commit()
    return await load_task(session, task_id)


async def create_adhoc_task(
    session: AsyncSession,
    engagement_id: uuid.UUID,
    title: str,
    due_date: date | None,
    assignee_id: uuid.UUID | None,
    actor_id: uuid.UUID,
) -> Task:
    """A task a manager adds by hand, outside the service's templates.

    task_template_id is null, which is what marks it ad-hoc. Because the
    recurrence generator reads templates and never reads the previous period's
    tasks, an ad-hoc task is structurally excluded from carrying forward — the
    exclusion needs no flag anyone has to remember to set.
    """
    engagement = await session.get(Engagement, engagement_id)
    if engagement is None or engagement.deleted_at is not None:
        raise NotFoundError("Engagement not found")

    highest_sequence = await session.scalar(
        select(func.coalesce(func.max(Task.sequence), 0)).where(
            Task.engagement_id == engagement_id
        )
    )

    if assignee_id is not None and assignee_id == engagement.manager_id:
        raise ConflictError(
            "The assignee and the reviewer cannot be the same person"
        )

    if assignee_id is not None:
        await _require_active_user(session, assignee_id, "Assignee")

    task = Task(
        engagement_id=engagement_id,
        task_template_id=None,
        title=title,
        sequence=highest_sequence + 1,
        status=TaskStatus.ASSIGNED if assignee_id else TaskStatus.NOT_STARTED,
        assignee_id=assignee_id,
        reviewer_id=engagement.manager_id,
        due_date=due_date,
        updated_by=actor_id,
    )
    session.add(task)
    await session.commit()
    return await load_task(session, task.id)


async def soft_delete_task(
    session: AsyncSession,
    task_id: uuid.UUID,
    reason: str,
    actor_id: uuid.UUID,
    actor_role: UserRole,
) -> Task:
    """Deletion is a separate axis from workflow status, not a status value.

    If `deleted` were an eighth TaskStatus it would overwrite whatever state the
    task was in, and restore would have nowhere to put it back to. Keeping it
    separate means a deleted task retains its status and restore returns it
    exactly where it was.

    A soft delete is an UPDATE, so deleted_by names the actual deleter. On a
    hard DELETE the audit trigger would only have OLD.updated_by, which is
    whoever last edited the row.
    """
    task = await load_task(session, task_id)
    _require_reviewer_or_admin(task, actor_id, actor_role)
    task.deleted_at = datetime.now(timezone.utc)
    task.deleted_by = actor_id
    task.deletion_reason = reason
    task.updated_by = actor_id
    await session.commit()
    return await load_task(session, task_id, include_deleted=True)


async def restore_task(
    session: AsyncSession, task_id: uuid.UUID, actor_id: uuid.UUID, actor_role: UserRole
) -> Task:
    task = await load_task(session, task_id, include_deleted=True)
    _require_reviewer_or_admin(task, actor_id, actor_role)
    if task.deleted_at is None:
        raise ConflictError("This task is not deleted")

    task.deleted_at = None
    task.deleted_by = None
    task.deletion_reason = None
    task.updated_by = actor_id
    await session.commit()
    return await load_task(session, task_id)
