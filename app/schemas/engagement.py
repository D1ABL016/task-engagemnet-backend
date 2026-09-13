import uuid
from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, model_validator

from app.models.enums import EngagementType, RecurrenceFrequency


class EngagementUpdate(BaseModel):
    """Only `manager_id` and `auto_renew` may actually change after creation.

    `client_id`, `service_type_id`, `period_start` and `engagement_type` are
    accepted here only so the service can tell "the client resubmitted the
    same value" from "the client is trying to change this" and reject the
    latter with a 409 naming the reason, rather than a validation error or a
    value that is silently ignored. Changing any of them after tasks exist
    would leave generated tasks describing work that no longer matches their
    engagement, and would move the row under `engagement_unique_period`.
    """

    manager_id: uuid.UUID | None = None
    auto_renew: bool | None = None
    client_id: uuid.UUID | None = None
    service_type_id: uuid.UUID | None = None
    period_start: date | None = None
    engagement_type: EngagementType | None = None


class EngagementCreate(BaseModel):
    client_id: uuid.UUID
    service_type_id: uuid.UUID
    manager_id: uuid.UUID
    engagement_type: EngagementType
    recurrence: RecurrenceFrequency | None = None
    start_date: date

    @model_validator(mode="after")
    def check_recurrence_matches_type(self) -> "EngagementCreate":
        """Mirrors the engagement_recurring_has_period check constraint.

        Caught here so the caller gets a 422 naming the field, rather than a
        constraint violation from the database.
        """
        if self.engagement_type is EngagementType.RECURRING and self.recurrence is None:
            raise ValueError("A recurring engagement must specify a recurrence")
        if self.engagement_type is EngagementType.ONE_TIME and self.recurrence is not None:
            raise ValueError("A one-time engagement must not specify a recurrence")
        return self


class TaskSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    title: str
    sequence: int
    status: str
    assignee_id: uuid.UUID | None
    reviewer_id: uuid.UUID
    due_date: date | None


class EngagementResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    client_id: uuid.UUID
    service_type_id: uuid.UUID
    manager_id: uuid.UUID
    engagement_type: EngagementType
    recurrence: RecurrenceFrequency | None
    start_date: date
    period_start: date | None
    period_end: date | None
    auto_renew: bool
    deleted_at: datetime | None = None
    deletion_reason: str | None = None
    tasks: list[TaskSummary] = []


class GenerateNextResponse(BaseModel):
    created: bool
    engagement: EngagementResponse


class AutoRenewRequest(BaseModel):
    enabled: bool
