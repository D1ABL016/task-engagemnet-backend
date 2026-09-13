import uuid
from datetime import date, datetime

from sqlalchemy import (
    CheckConstraint, Date, DateTime, Enum as SAEnum, ForeignKey, Index,
    Integer, String, Text, func, text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import AuditMixin, Base, SoftDeleteMixin, TimestampMixin
from app.models.enums import ReviewDecision, TaskStatus


class Task(Base, TimestampMixin, AuditMixin, SoftDeleteMixin):
    __tablename__ = "task"
    __table_args__ = (
        CheckConstraint(
            "assignee_id IS NULL OR assignee_id <> reviewer_id",
            name="task_reviewer_is_not_assignee",
        ),
        Index(
            "task_engagement_active_idx",
            "engagement_id",
            postgresql_where=text("deleted_at IS NULL"),
        ),
        Index(
            "task_assignee_status_idx",
            "assignee_id",
            "status",
            postgresql_where=text("deleted_at IS NULL"),
        ),
        Index(
            "task_deleted_idx",
            "deleted_at",
            postgresql_where=text("deleted_at IS NOT NULL"),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    engagement_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("engagement.id"), nullable=False
    )
    task_template_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("task_template.id"), nullable=True
    )
    title: Mapped[str] = mapped_column(String(300), nullable=False)
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[TaskStatus] = mapped_column(
        SAEnum(TaskStatus, name="task_status",
               values_callable=lambda e: [m.value for m in e]),
        nullable=False,
        default=TaskStatus.NOT_STARTED,
    )
    assignee_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("app_user.id"), nullable=True
    )
    reviewer_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("app_user.id"), nullable=False
    )
    due_date: Mapped[date | None] = mapped_column(Date, nullable=True)

    #: One-directional: the reverse (`Engagement.tasks`) is a separate,
    #: viewonly relationship filtered to non-deleted tasks (see
    #: `app/models/engagement.py`), so the two are not paired via
    #: back_populates.
    engagement: Mapped["Engagement"] = relationship()
    reviews: Mapped[list["TaskReview"]] = relationship(
        back_populates="task", order_by="TaskReview.created_at"
    )


class TaskReview(Base):
    """One row per review action. The user-facing record of what happened.

    Not derived from the audit tables: those are row-diffs written by triggers
    that cannot see the JWT, they would require inferring a decision from the
    destination status, and once the UI reads them their shape is frozen.
    """

    __tablename__ = "task_review"
    __table_args__ = (
        CheckConstraint(
            "decision = 'approved' OR (comment IS NOT NULL AND length(btrim(comment)) > 0)",
            name="task_review_comment_required_when_negative",
        ),
        Index("task_review_task_idx", "task_id", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    task_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("task.id"), nullable=False
    )
    reviewer_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("app_user.id"), nullable=False
    )
    decision: Mapped[ReviewDecision] = mapped_column(
        SAEnum(ReviewDecision, name="review_decision",
               values_callable=lambda e: [m.value for m in e]),
        nullable=False,
    )
    comment: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    task: Mapped[Task] = relationship(back_populates="reviews")
