from datetime import datetime

from sqlalchemy import DateTime, Integer, String
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from levelup.core.db import Base


class ImportBatch(Base):
    __tablename__ = "import_batches"

    id: Mapped[int] = mapped_column(primary_key=True)
    source_label: Mapped[str] = mapped_column(String, nullable=False)
    source_url: Mapped[str] = mapped_column(String, nullable=False)
    file_sha256: Mapped[str] = mapped_column(String, nullable=False)
    downloaded_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    imported_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    row_count_total: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    row_count_imported: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    row_count_excluded_adult: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    row_count_excluded_other_type: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    row_count_errors: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    status: Mapped[str] = mapped_column(String, nullable=False, default="pending")

    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
