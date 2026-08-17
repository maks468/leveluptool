from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func

from levelup.core.db import Base


class Campaign(Base):
    """A named batch of schools carved OUT of the pipeline -- e.g. "the 80
    Mazowieckie primaries getting the September mailing". Deliberately a
    storage container, not a workflow: nothing is ever sent from here, no
    stages, no follow-ups, no automation -- if campaigns ever grow real
    sending behaviour, that plugs into services/automation, not here.

    The point of the container is double-contact protection: every school
    lives in exactly ONE place -- the Library only, the pipeline, or one
    campaign. Moving here deletes the school's PipelineState row, a school
    can belong to at most one campaign (school_id is unique across
    memberships), and pull-into-pipeline skips campaign members. The only
    way out is the explicit return-to-pipeline action."""

    __tablename__ = "campaigns"

    id: Mapped[int] = mapped_column(primary_key=True)
    owner_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    name: Mapped[str] = mapped_column(String, unique=True, nullable=False)
    # Free-form note about what this batch IS ("wysyłka wrzesień, mazowieckie
    # 70+, template B") -- the container's label explains which schools,
    # this explains why/what was sent. Optional.
    description: Mapped[str | None] = mapped_column(String, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    schools: Mapped[list["CampaignSchool"]] = relationship(
        back_populates="campaign", cascade="all, delete-orphan"
    )


class CampaignSchool(Base):
    """Membership row, school <-> campaign. stage_at_move snapshots the
    pipeline stage the school had when it was moved -- the PipelineState row
    it came from is deleted, so without this the batch would lose the one
    piece of pursuit context worth keeping ("these were all CONTACTED"),
    and returning a school to the pipeline couldn't restore where it was."""

    __tablename__ = "campaign_schools"

    id: Mapped[int] = mapped_column(primary_key=True)
    campaign_id: Mapped[int] = mapped_column(ForeignKey("campaigns.id"), nullable=False, index=True)
    # Unique across ALL campaigns, not per-campaign -- a school in two
    # campaigns is exactly the double-contact the container exists to
    # prevent.
    school_id: Mapped[int] = mapped_column(ForeignKey("schools.id"), nullable=False, unique=True, index=True)
    stage_at_move: Mapped[str] = mapped_column(String, nullable=False, default="not_contacted")
    added_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    campaign: Mapped["Campaign"] = relationship(back_populates="schools")
    # Read-only convenience for listing a campaign's schools without a
    # second query per row (eager-loaded where listed).
    school = relationship("School", viewonly=True)
