from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func

from levelup.core.db import Base


class EnrichmentJob(Base):
    __tablename__ = "enrichment_jobs"

    id: Mapped[int] = mapped_column(primary_key=True)
    requested_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    requested_by: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    status: Mapped[str] = mapped_column(String, nullable=False, default="pending")  # pending|running|done|cancelled
    # True for jobs the background auto-enrich cycle created itself, so the
    # job tray/activity log can distinguish "the system did this overnight"
    # from a batch you explicitly selected and ran.
    is_automatic: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    # Set by the Stop button, checked by run_job between schools -- the
    # currently-running school always finishes (never killed mid-scrape),
    # but every remaining "pending" item is skipped rather than started.
    cancel_requested: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    items: Mapped[list["EnrichmentJobItem"]] = relationship(back_populates="job")


class EnrichmentJobItem(Base):
    __tablename__ = "enrichment_job_items"

    id: Mapped[int] = mapped_column(primary_key=True)
    job_id: Mapped[int] = mapped_column(ForeignKey("enrichment_jobs.id"), nullable=False, index=True)
    school_id: Mapped[int] = mapped_column(ForeignKey("schools.id"), nullable=False, index=True)
    status: Mapped[str] = mapped_column(
        String, nullable=False, default="pending"
    )  # pending|running|success|failed|cancelled
    error_message: Mapped[str | None] = mapped_column(String, nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    job: Mapped["EnrichmentJob"] = relationship(back_populates="items")
    # Read-only -- lets the batch job tray show "Szkoła Podstawowa..." instead
    # of an opaque "School #1011"; eager-loaded via joinedload where listed
    # to avoid an N+1 query per item.
    school: Mapped["School"] = relationship(viewonly=True)

    @property
    def school_name(self) -> str:
        return self.school.name

    @property
    def school_city(self) -> str | None:
        return self.school.city


class SchoolContact(Base):
    """Deeper enrichment output. `contact_quality` is computed (never set
    directly by the UI) from what was actually found:
    - "failed": no named person found at all (an unnamed office email
      doesn't count as a contact)
    - "partial": a named person was found, but no personal email for them
    - "verified": a named person AND their own email, both found
    """

    __tablename__ = "school_contacts"

    id: Mapped[int] = mapped_column(primary_key=True)
    school_id: Mapped[int] = mapped_column(ForeignKey("schools.id"), nullable=False, index=True)
    contact_type: Mapped[str] = mapped_column(String, nullable=False)  # director|english_coordinator
    person_name: Mapped[str | None] = mapped_column(String, nullable=True)
    email: Mapped[str | None] = mapped_column(String, nullable=True)
    phone: Mapped[str | None] = mapped_column(String, nullable=True)
    source_url: Mapped[str | None] = mapped_column(String, nullable=True)
    captured_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    enrichment_job_id: Mapped[int | None] = mapped_column(ForeignKey("enrichment_jobs.id"), nullable=True)
    contact_quality: Mapped[str] = mapped_column(String, nullable=False, default="failed")
