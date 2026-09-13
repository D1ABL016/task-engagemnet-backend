from pydantic import BaseModel


class DashboardSummary(BaseModel):
    """Counts for the sections the assignment asks for, plus two the workflow
    makes free: unassigned work, and work that came back and nobody resumed."""

    unassigned: int
    open_tasks: int
    due_today: int
    overdue: int
    waiting_for_client: int
    waiting_for_review: int
    needs_rework: int
    upcoming: int
    deleted: int
