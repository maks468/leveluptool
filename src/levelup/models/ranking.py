from datetime import datetime

from sqlalchemy import JSON, DateTime, Float, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from levelup.core.db import Base


class RankingCache(Base):
    """One row per (source, year) PDF we've parsed. Kept so a parser bug
    can be fixed and re-run without re-fetching the PDF."""

    __tablename__ = "ranking_cache"

    id: Mapped[int] = mapped_column(primary_key=True)
    source: Mapped[str] = mapped_column(String, nullable=False)  # "perspektywy_licea" | "perspektywy_technika"
    ranking_year: Mapped[int] = mapped_column(Integer, nullable=False)
    source_pdf_path: Mapped[str] = mapped_column(String, nullable=False)
    source_pdf_sha256: Mapped[str] = mapped_column(String, nullable=False)
    parsed_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class RankingEntry(Base):
    __tablename__ = "ranking_entries"

    id: Mapped[int] = mapped_column(primary_key=True)
    ranking_cache_id: Mapped[int] = mapped_column(ForeignKey("ranking_cache.id"), nullable=False, index=True)
    rank: Mapped[int] = mapped_column(Integer, nullable=False)
    school_name_raw: Mapped[str] = mapped_column(String, nullable=False)
    city_raw: Mapped[str] = mapped_column(String, nullable=False)
    voivodeship_raw: Mapped[str | None] = mapped_column(String, nullable=True)
    extra: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)


class SchoolRankingMatch(Base):
    """Fuzzy match cache between a school and a ranking entry. Scoring
    reads only confirmed matches — matching is refreshed on ranking
    re-import, never re-run inside a plain rescore."""

    __tablename__ = "school_ranking_matches"

    id: Mapped[int] = mapped_column(primary_key=True)
    school_id: Mapped[int] = mapped_column(ForeignKey("schools.id"), nullable=False, index=True)
    ranking_entry_id: Mapped[int] = mapped_column(ForeignKey("ranking_entries.id"), nullable=False)
    ranking_year: Mapped[int] = mapped_column(Integer, nullable=False)
    match_confidence: Mapped[float] = mapped_column(Float, nullable=False)
    match_status: Mapped[str] = mapped_column(String, nullable=False, default="auto")  # auto|confirmed|rejected
    matched_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
