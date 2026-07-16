import enum
from datetime import datetime

from sqlalchemy import JSON, DateTime, Enum, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from levelup.core.db import Base


class PipelineStage(str, enum.Enum):
    NOT_CONTACTED = "not_contacted"
    CONTACTED = "contacted"
    RESPONDED = "responded"
    MEETING_BOOKED = "meeting_booked"
    MEETING_HELD = "meeting_held"
    NEXT_STEP_AGREED = "next_step_agreed"
    WON = "won"
    LOST = "lost"


class ActivityType(str, enum.Enum):
    NOTE = "note"
    STAGE_CHANGED = "stage_changed"
    ENRICHMENT_COMPLETED = "enrichment_completed"
    OWNERSHIP_SUBTYPE_CONFIRMED = "ownership_subtype_confirmed"
    PULLED_INTO_PIPELINE = "pulled_into_pipeline"
    # Reserved, unused until automation ships — added now so the enum grows
    # additively later instead of breaking existing consumers.
    EMAIL_SENT = "email_sent"
    EMAIL_OPENED = "email_opened"
    REMINDER_SCHEDULED = "reminder_scheduled"


class PipelineState(Base):
    """Exists only for schools actively pursued. owner_id is the
    multi-user seam — defaulted to the single seeded user today."""

    __tablename__ = "pipeline_state"

    school_id: Mapped[int] = mapped_column(ForeignKey("schools.id"), primary_key=True)
    owner_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    stage: Mapped[PipelineStage] = mapped_column(Enum(PipelineStage), nullable=False, default=PipelineStage.NOT_CONTACTED)
    entered_pipeline_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    stage_updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())
    next_action_note: Mapped[str | None] = mapped_column(String, nullable=True)
    next_action_date: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class ActivityLog(Base):
    """Append-only — no update/delete exposed anywhere in the service or
    API layer. Keyed off school_id (not pipeline membership) so it can
    capture pre-pipeline system events like ownership confirmation."""

    __tablename__ = "activity_log"

    id: Mapped[int] = mapped_column(primary_key=True)
    school_id: Mapped[int] = mapped_column(ForeignKey("schools.id"), nullable=False, index=True)
    actor_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)  # null = system
    activity_type: Mapped[str] = mapped_column(String, nullable=False)
    from_stage: Mapped[str | None] = mapped_column(String, nullable=True)
    to_stage: Mapped[str | None] = mapped_column(String, nullable=True)
    note: Mapped[str | None] = mapped_column(String, nullable=True)
    metadata_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    occurred_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
