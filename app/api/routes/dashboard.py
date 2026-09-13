from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import CurrentUser, require_any_role
from app.database import get_session
from app.schemas.dashboard import DashboardSummary
from app.services.dashboard_service import build_dashboard

router = APIRouter(prefix="/api/v1/dashboard", tags=["dashboard"])


@router.get("", response_model=DashboardSummary)
async def read_dashboard(
    current_user: CurrentUser = Depends(require_any_role),
    session: AsyncSession = Depends(get_session),
) -> DashboardSummary:
    return await build_dashboard(session, current_user.id, current_user.is_manager_or_admin)
