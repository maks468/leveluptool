from datetime import datetime

from sqlalchemy import Boolean, CheckConstraint, DateTime, Integer
from sqlalchemy.orm import Mapped, mapped_column

from levelup.core.db import Base


class AutoEnrichSettings(Base):
    """Singleton row (id is always 1) controlling the background
    auto-enrichment thread -- how many schools it enriches per cycle, how
    often, and whether it's on at all. A row is created with sensible
    defaults the first time it's read; nothing else ever inserts here."""

    __tablename__ = "auto_enrich_settings"
    __table_args__ = (CheckConstraint("id = 1", name="ck_auto_enrich_settings_singleton"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, default=1)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    schools_per_run: Mapped[int] = mapped_column(Integer, nullable=False, default=20)
    interval_minutes: Mapped[int] = mapped_column(Integer, nullable=False, default=60)
    last_run_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_run_found_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
