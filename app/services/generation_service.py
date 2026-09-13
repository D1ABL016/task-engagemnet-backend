import logging
import uuid
from dataclasses import dataclass
from datetime import date, timedelta

from sqlalchemy import and_, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.core.errors import ConflictError
from app.core.periods import next_period
from app.models.client import Client
from app.models.engagement import Engagement
from app.models.enums import EngagementType, TaskStatus
from app.models.service_type import ServiceType, TaskTemplate
from app.models.task import Task

logger = logging.getLogger(__name__)


async def generate_tasks_for_engagement(
    session: AsyncSession, engagement: Engagement
) -> list[Task]:
    """Create one task per template of the engagement's service type.

    Title, sequence and the resolved due date are COPIED onto each task rather
    than read through the template at display time. A template is a recipe; a
    task is a snapshot taken when the engagement was created. If tasks joined to
    templates for their title, an admin fixing a typo would silently rewrite
    every historical task in every past period.

    Does not commit. The caller owns the transaction, so the engagement and its
    tasks land together or not at all.
    """
    result = await session.execute(
        select(TaskTemplate)
        .where(TaskTemplate.service_type_id == engagement.service_type_id)
        .order_by(TaskTemplate.sequence)
    )
    templates = list(result.scalars().all())

    if not templates:
        raise ConflictError(
            "This service type has no task templates, so the engagement would "
            "have no work in it"
        )

    tasks: list[Task] = []
    for template in templates:
        task = Task(
            engagement_id=engagement.id,
            task_template_id=template.id,
            title=template.title,
            sequence=template.sequence,
            status=TaskStatus.NOT_STARTED,
            assignee_id=None,
            reviewer_id=engagement.manager_id,
            due_date=engagement.start_date + timedelta(days=template.default_offset_days),
            updated_by=engagement.updated_by,
        )
        session.add(task)
        tasks.append(task)

    return tasks


@dataclass
class GenerationRunSummary:
    created: int = 0
    skipped: int = 0
    failed: int = 0


async def find_series_due_for_generation(
    session: AsyncSession, as_of: date
) -> list[Engagement]:
    """Return the latest engagement of each recurring series that is now due.

    A series is implicit: the set of engagements sharing a client and service
    type, which is exactly what the unique index already treats as a series. A
    previous_engagement_id column would duplicate that with something that can
    break, and a broken link would silently stop a series recurring forever.
    """
    settings = get_settings()
    cutoff = as_of + timedelta(days=settings.recurrence_lead_days)

    latest_period = (
        select(
            Engagement.client_id,
            Engagement.service_type_id,
            func.max(Engagement.period_start).label("latest_period_start"),
        )
        .where(
            Engagement.engagement_type == EngagementType.RECURRING,
            Engagement.deleted_at.is_(None),
        )
        .group_by(Engagement.client_id, Engagement.service_type_id)
        .subquery()
    )

    result = await session.execute(
        select(Engagement)
        .join(
            latest_period,
            and_(
                Engagement.client_id == latest_period.c.client_id,
                Engagement.service_type_id == latest_period.c.service_type_id,
                Engagement.period_start == latest_period.c.latest_period_start,
            ),
        )
        .join(Client, Client.id == Engagement.client_id)
        .join(ServiceType, ServiceType.id == Engagement.service_type_id)
        .where(
            Engagement.auto_renew.is_(True),
            Engagement.deleted_at.is_(None),
            Client.is_active.is_(True),
            Client.deleted_at.is_(None),
            ServiceType.is_active.is_(True),
            ServiceType.deleted_at.is_(None),
        )
    )

    due: list[Engagement] = []
    for engagement in result.scalars().all():
        following_start, _ = next_period(engagement.recurrence, engagement.period_start)
        if following_start <= cutoff:
            due.append(engagement)
    return due


async def create_next_period(
    session: AsyncSession, engagement: Engagement, actor_id: uuid.UUID | None
) -> tuple[bool, Engagement]:
    """Create the engagement following the given one. Idempotent.

    Returns (created, engagement). When the next period already exists, returns
    (False, the existing one) rather than raising: the caller's intent is
    already satisfied.

    One transaction covers the engagement and its tasks. An engagement with only
    half its tasks would look complete to every later run, because the only
    existence check is on the engagement itself.
    """
    following_start, following_end = next_period(
        engagement.recurrence, engagement.period_start
    )

    # Captured up front: after a rollback below, the ORM instance passed in is
    # expired, and touching its attributes then would trigger an implicit
    # refresh outside of an awaited context.
    client_id = engagement.client_id
    service_type_id = engagement.service_type_id

    next_engagement = Engagement(
        client_id=client_id,
        service_type_id=service_type_id,
        manager_id=engagement.manager_id,
        engagement_type=EngagementType.RECURRING,
        recurrence=engagement.recurrence,
        start_date=following_start,
        period_start=following_start,
        period_end=following_end,
        auto_renew=engagement.auto_renew,
        updated_by=actor_id,
    )
    session.add(next_engagement)

    try:
        await session.flush()
        await generate_tasks_for_engagement(session, next_engagement)
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        if next_engagement in session:
            session.expunge(next_engagement)
        if "engagement_unique_period" not in str(exc.orig):
            raise
        existing = await session.execute(
            select(Engagement).where(
                Engagement.client_id == client_id,
                Engagement.service_type_id == service_type_id,
                Engagement.period_start == following_start,
                Engagement.deleted_at.is_(None),
            )
        )
        return False, existing.scalar_one()

    return True, next_engagement


async def run_recurrence_generation(
    session_factory, as_of: date
) -> GenerationRunSummary:
    """One transaction per engagement, so one bad series cannot stop the rest.

    A whole-run transaction would roll back every client's engagements because
    of one broken service type, and hold locks for the duration of the run.
    """
    summary = GenerationRunSummary()

    async with session_factory() as session:
        due_engagements = await find_series_due_for_generation(session, as_of)
        due_ids = [engagement.id for engagement in due_engagements]

    for engagement_id in due_ids:
        async with session_factory() as session:
            try:
                engagement = await session.get(Engagement, engagement_id)
                created, _ = await create_next_period(session, engagement, actor_id=None)
                if created:
                    summary.created += 1
                else:
                    summary.skipped += 1
            except Exception:
                await session.rollback()
                summary.failed += 1
                logger.exception(
                    "Recurrence generation failed for engagement %s", engagement_id
                )

    logger.info(
        "Recurrence run complete: created=%d skipped=%d failed=%d",
        summary.created,
        summary.skipped,
        summary.failed,
    )
    return summary
