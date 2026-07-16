from datetime import datetime

from sqlalchemy import JSON, Boolean, DateTime, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from levelup.core.db import Base


class SavedView(Base):
    """A named, revisitable filter+sort combination -- Twenty CRM's "Views"
    concept, and the single highest-leverage CRM gap identified for this
    project: without it, filters reset every session, which doesn't scale
    once you're systematically working through 25k+ schools over time
    rather than just finding one shortlist. owner_id is the same multi-user
    seam used elsewhere (single seeded user today). `scope` distinguishes
    Library views (filters_json shaped like LibraryFilters) from Pipeline
    views (a different filter shape) -- both share this one table since
    the payload is already schema-less JSON."""

    __tablename__ = "saved_views"

    id: Mapped[int] = mapped_column(primary_key=True)
    owner_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    name: Mapped[str] = mapped_column(String, nullable=False)
    scope: Mapped[str] = mapped_column(String, nullable=False, default="library")
    filters_json: Mapped[dict] = mapped_column(JSON, nullable=False)
    sort: Mapped[str | None] = mapped_column(String, nullable=True)
    result_limit: Mapped[int | None] = mapped_column(Integer, nullable=True)
    is_favorite: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())


class Tag(Base):
    """Free-form, multi-select labels independent of pipeline stage --
    Twenty CRM's tagging pattern, for nuance that doesn't fit the linear
    stage model ("has EU funding", "revisit next spring", "gatekeeper is
    hostile")."""

    __tablename__ = "tags"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String, unique=True, nullable=False)
    color: Mapped[str] = mapped_column(String, nullable=False, default="slate")
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class SchoolTag(Base):
    """Many-to-many join, school <-> tag."""

    __tablename__ = "school_tags"
    __table_args__ = (UniqueConstraint("school_id", "tag_id", name="uq_school_tag"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    school_id: Mapped[int] = mapped_column(ForeignKey("schools.id"), nullable=False, index=True)
    tag_id: Mapped[int] = mapped_column(ForeignKey("tags.id"), nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
