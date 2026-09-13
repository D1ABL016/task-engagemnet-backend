from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_session

router = APIRouter(tags=["health"])


@router.get("/health")
async def health_check(session: AsyncSession = Depends(get_session)) -> dict[str, str]:
    """Unauthenticated liveness probe.

    Deliberately outside every auth dependency: UptimeRobot pings this every
    five minutes to stop the free-tier instance sleeping, which would otherwise
    stop the recurrence job from firing. It touches the database so the ping
    also keeps the Neon compute awake.
    """
    await session.execute(text("SELECT 1"))
    return {"status": "ok"}
