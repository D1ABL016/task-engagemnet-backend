import uuid
from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, Field

from app.models.enums import ReviewDecision, TaskStatus


class ReviewCommentRequired(BaseModel):
    """For request-changes and reopen: the team member must be told why."""

    comment: str = Field(min_length=1, max_length=2000)


class ReviewCommentOptional(BaseModel):
    """For approve: praise is welcome but not compulsory."""

    comment: str | None = Field(default=None, max_length=2000)


class TaskReviewResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    reviewer_id: uuid.UUID
    decision: ReviewDecision
    comment: str | None
    created_at: datetime


class TaskResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    engagement_id: uuid.UUID
    task_template_id: uuid.UUID | None
    title: str
    sequence: int
    status: TaskStatus
    assignee_id: uuid.UUID | None
    reviewer_id: uuid.UUID
    due_date: date | None
    deleted_at: datetime | None
    deletion_reason: str | None
    reviews: list[TaskReviewResponse] = []


class AssignmentRequest(BaseModel):
    assignee_id: uuid.UUID | None = None
    reviewer_id: uuid.UUID | None = None


class DeadlineRequest(BaseModel):
    due_date: date | None = None


class AdHocTaskCreate(BaseModel):
    title: str = Field(min_length=1, max_length=300)
    due_date: date | None = None
    assignee_id: uuid.UUID | None = None


class DeletionRequest(BaseModel):
    reason: str = Field(min_length=1, max_length=500)
