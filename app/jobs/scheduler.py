import logging

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from app.jobs.recurrence_job import run_daily_recurrence_job

logger = logging.getLogger(__name__)


def create_scheduler() -> AsyncIOScheduler:
    """AsyncIOScheduler so jobs share the app's event loop and its async session."""
    scheduler = AsyncIOScheduler(timezone="UTC")
    scheduler.add_job(
        run_daily_recurrence_job,
        trigger=CronTrigger(hour=2, minute=0),
        id="daily_recurrence_generation",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
    )
    return scheduler
