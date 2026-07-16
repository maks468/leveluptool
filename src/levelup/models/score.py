import enum
from datetime import datetime

from sqlalchemy import JSON, DateTime, Enum, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from levelup.core.db import Base


class RubricType(str, enum.Enum):
    PRIMARY = "primary"
    SECONDARY = "secondary"


class SchoolScore(Base):
    """Append-only score history. Rescoring always inserts a new row, even
    at an unchanged rubric_version, and never touches `schools`."""

    __tablename__ = "school_scores"

    id: Mapped[int] = mapped_column(primary_key=True)
    school_id: Mapped[int] = mapped_column(ForeignKey("schools.id"), nullable=False, index=True)
    rubric_type: Mapped[RubricType] = mapped_column(Enum(RubricType), nullable=False)
    rubric_version: Mapped[str] = mapped_column(String, nullable=False)

    total_score: Mapped[int | None] = mapped_column(Integer, nullable=True)
    criterion_breakdown: Mapped[dict] = mapped_column(JSON, nullable=False)

    computed_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class CurrentScore(Base):
    """Pointer to the latest score per (school, rubric) — avoids scanning
    history to find 'the' current score."""

    __tablename__ = "current_scores"

    school_id: Mapped[int] = mapped_column(ForeignKey("schools.id"), primary_key=True)
    rubric_type: Mapped[RubricType] = mapped_column(Enum(RubricType), primary_key=True)
    score_id: Mapped[int] = mapped_column(ForeignKey("school_scores.id"), nullable=False)
