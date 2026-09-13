import logging
from datetime import date

from app.database import async_session_factory
from app.services.generation_service import run_recurrence_generation

logger = logging.getLogger(__name__)


async def run_daily_recurrence_job() -> None:
    """Thin wrapper. All logic lives in the service the API also calls."""
    logger.info("Starting daily recurrence generation")
    summary = await run_recurrence_generation(async_session_factory, as_of=date.today())
    logger.info(
        "Daily recurrence generation finished: created=%d skipped=%d failed=%d",
        summary.created,
        summary.skipped,
        summary.failed,
    )
