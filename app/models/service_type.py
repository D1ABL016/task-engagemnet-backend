import uuid

from sqlalchemy import Boolean, CheckConstraint, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import AuditMixin, Base, SoftDeleteMixin, TimestampMixin


class ServiceType(Base, TimestampMixin, AuditMixin, SoftDeleteMixin):
    """A service the firm offers. A catalogue entry and nothing more.

    Recurrence deliberately does not live here: the same service can be sold as
    an ongoing arrangement or as a one-off, so cadence belongs to the
    engagement.
    """

    __tablename__ = "service_type"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False, unique=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    task_templates: Mapped[list["TaskTemplate"]] = relationship(
        back_populates="service_type", order_by="TaskTemplate.sequence"
    )


class TaskTemplate(Base, TimestampMixin, AuditMixin):
    __tablename__ = "task_template"
    __table_args__ = (
        UniqueConstraint(
            "service_type_id",
            "sequence",
            name="task_template_sequence_unique",
            deferrable=True,
            initially="DEFERRED",
        ),
        CheckConstraint(
            "default_offset_days >= 0", name="task_template_offset_non_negative"
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    service_type_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("service_type.id"), nullable=False
    )
    title: Mapped[str] = mapped_column(String(300), nullable=False)
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    default_offset_days: Mapped[int] = mapped_column(Integer, nullable=False)

    service_type: Mapped[ServiceType] = relationship(back_populates="task_templates")
