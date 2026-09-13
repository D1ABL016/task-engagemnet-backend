import enum


class UserRole(str, enum.Enum):
    ADMIN = "admin"
    MANAGER = "manager"
    TEAM_MEMBER = "team_member"


class TaskStatus(str, enum.Enum):
    NOT_STARTED = "not_started"
    ASSIGNED = "assigned"
    IN_PROGRESS = "in_progress"
    WAITING_FOR_CLIENT = "waiting_for_client"
    READY_FOR_REVIEW = "ready_for_review"
    CHANGES_REQUESTED = "changes_requested"
    COMPLETED = "completed"


class ReviewDecision(str, enum.Enum):
    APPROVED = "approved"
    CHANGES_REQUESTED = "changes_requested"
    REOPENED = "reopened"


class EngagementType(str, enum.Enum):
    ONE_TIME = "one_time"
    RECURRING = "recurring"


class RecurrenceFrequency(str, enum.Enum):
    MONTHLY = "monthly"
    QUARTERLY = "quarterly"
    ANNUAL = "annual"
