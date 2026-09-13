import uuid
from datetime import date

from sqlalchemy import Boolean, CheckConstraint, Date, Enum as SAEnum, ForeignKey, Index, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import AuditMixin, Base, SoftDeleteMixin, TimestampMixin
from app.models.enums import EngagementType, RecurrenceFrequency


class Engagement(Base, TimestampMixin, AuditMixin, SoftDeleteMixin):
    __tablename__ = "engagement"
    __table_args__ = (
        CheckConstraint(
            "(engagement_type = 'recurring' AND recurrence IS NOT NULL "
            " AND period_start IS NOT NULL AND period_end IS NOT NULL) "
            "OR (engagement_type = 'one_time' AND recurrence IS NULL "
            " AND period_start IS NULL AND period_end IS NULL)",
            name="engagement_recurring_has_period",
        ),
        CheckConstraint(
            "period_start IS NULL OR period_end > period_start",
            name="engagement_period_ordered",
        ),
        CheckConstraint(
            "period_start IS NULL OR start_date = period_start",
            name="engagement_start_matches_period",
        ),
        Index(
            "engagement_unique_period",
            "client_id",
            "service_type_id",
            "period_start",
            unique=True,
            postgresql_where=text("period_start IS NOT NULL AND deleted_at IS NULL"),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    client_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("client.id"), nullable=False
    )
    service_type_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("service_type.id"), nullable=False
    )
    manager_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("app_user.id"), nullable=False
    )
    engagement_type: Mapped[EngagementType] = mapped_column(
        SAEnum(EngagementType, name="engagement_type",
               values_callable=lambda e: [m.value for m in e]),
        nullable=False,
    )
    recurrence: Mapped[RecurrenceFrequency | None] = mapped_column(
        SAEnum(RecurrenceFrequency, name="recurrence_frequency",
               values_callable=lambda e: [m.value for m in e]),
        nullable=True,
    )
    start_date: Mapped[date] = mapped_column(Date, nullable=False)
    period_start: Mapped[date | None] = mapped_column(Date, nullable=True)
    period_end: Mapped[date | None] = mapped_column(Date, nullable=True)
    auto_renew: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    #: viewonly + a filtered primaryjoin: soft-deleted tasks must never appear
    #: in an engagement's embedded task list. Tasks are created via
    #: `session.add(Task(...))`, never `engagement.tasks.append(...)`, so the
    #: collection being read-only costs nothing.
    tasks: Mapped[list["Task"]] = relationship(
        primaryjoin="and_(Engagement.id == Task.engagement_id, "
        "Task.deleted_at.is_(None))",
        viewonly=True,
        order_by="Task.sequence",
    )
