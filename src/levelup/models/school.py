import enum
from datetime import datetime

from sqlalchemy import JSON, Boolean, DateTime, Enum, Float, ForeignKey, Index, Integer, String
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from levelup.core.db import Base


class SchoolLevel(str, enum.Enum):
    PRIMARY = "primary"
    LICEUM = "liceum"
    TECHNIKUM = "technikum"
    BRANZOWA_I = "branzowa_i"
    BRANZOWA_II = "branzowa_ii"
    POLICEALNA = "policealna"


class OwnershipSubtype(str, enum.Enum):
    NIEPUBLICZNA = "niepubliczna"
    SPOLECZNA = "spoleczna"
    MIEDZYNARODOWA = "miedzynarodowa"


class LanguageOrientation(str, enum.Enum):
    BILINGUAL = "bilingual"
    ENGLISH_FIRST_PLUS_EXTRA = "english_first_plus_extra"
    STANDARD_ENGLISH = "standard_english"


class EvidenceSource(str, enum.Enum):
    RSPO_NAME_MATCH = "rspo_name_match"
    RSPO_STRUCTURED_FIELD = "rspo_structured_field"
    ENRICHMENT = "enrichment"
    MANUAL = "manual"


class School(Base):
    """RSPO-sourced library core. Every nullable column here means
    genuinely unknown/unverified — never a placeholder. Re-import upserts
    on rspo_id and only ever touches these RSPO-sourced columns; it must
    never touch pipeline/activity/contact/score tables."""

    __tablename__ = "schools"
    __table_args__ = (
        # The dashboard's "active schools by level" breakdown filters on
        # is_active then groups by level -- with only single-column indexes
        # on each, SQLite can use the is_active index to find matching rows
        # but then has to fetch EVERY one of them from the main table just
        # to read `level` for the GROUP BY (confirmed directly: ~4s for
        # ~25,000 rows on this Windows/Docker bind-mounted setup, where
        # each such row fetch carries real cross-filesystem overhead, vs.
        # under 40ms for a plain COUNT the is_active index alone answers).
        # A composite index lets the GROUP BY resolve straight from the
        # index, no table lookups at all.
        Index("ix_schools_is_active_level", "is_active", "level"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    rspo_id: Mapped[str] = mapped_column(String, unique=True, nullable=False, index=True)

    name: Mapped[str] = mapped_column(String, nullable=False)
    level: Mapped[SchoolLevel] = mapped_column(Enum(SchoolLevel), nullable=False, index=True)

    voivodeship: Mapped[str | None] = mapped_column(String, nullable=True, index=True)
    city: Mapped[str | None] = mapped_column(String, nullable=True, index=True)

    is_private: Mapped[bool | None] = mapped_column(Boolean, nullable=True, index=True)
    ownership_subtype: Mapped[OwnershipSubtype | None] = mapped_column(
        Enum(OwnershipSubtype), nullable=True, index=True
    )
    ownership_subtype_verified: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    ownership_subtype_source: Mapped[EvidenceSource | None] = mapped_column(Enum(EvidenceSource), nullable=True)

    student_count: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)

    # Directly read off RSPO's "Kategoria uczniów" field ("Dorośli" or not) --
    # always determinate, never a guess, and orthogonal to level (an adult
    # learner cohort can exist within any of the levels above).
    is_adult_education: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, index=True)

    is_branch: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    has_grades_7_8: Mapped[bool | None] = mapped_column(Boolean, nullable=True)

    website_url: Mapped[str | None] = mapped_column(String, nullable=True)
    # None = came straight from RSPO's raw "Adres www" field, never
    # corrected. MANUAL/ENRICHMENT both outrank a stale or blank RSPO value
    # on re-import (see upsert.py) -- a human correction or a discovered URL
    # must survive the next nationwide re-import, not get silently reset.
    website_url_source: Mapped[EvidenceSource | None] = mapped_column(Enum(EvidenceSource), nullable=True)

    language_orientation: Mapped[LanguageOrientation | None] = mapped_column(
        Enum(LanguageOrientation), nullable=True
    )
    language_orientation_source: Mapped[EvidenceSource | None] = mapped_column(Enum(EvidenceSource), nullable=True)

    school_profile: Mapped[str | None] = mapped_column(String, nullable=True)

    director_name: Mapped[str | None] = mapped_column(String, nullable=True)
    english_teacher_name: Mapped[str | None] = mapped_column(String, nullable=True)

    # Special-education population the school serves (e.g. "Special-needs
    # school; Visual impairment"), detected during enrichment from the
    # school's own website and official name. Enrichment-sourced -- like
    # director_name above, re-import never writes it (map_row returns only
    # RSPO columns). None = nothing indicating a speciality was found.
    specialty: Mapped[str | None] = mapped_column(String, nullable=True)

    # Set ONLY for schools whose official name + city is NOT unique (e.g. the
    # several "BRANŻOWA SZKOŁA I STOPNIA W RADOMIU", each in a different
    # Zespół). Holds the extra bit that makes the display name unique -- the
    # parent complex (Zespół), or an "RSPO <id>" fallback when the complex
    # can't tell them apart. NULL for the ~99% whose name+city is already
    # unique. Recomputed by scripts/backfill_name_disambiguators.py.
    name_disambiguator: Mapped[str | None] = mapped_column(String, nullable=True)

    # From RSPO's own detail API (hqAddressGeotag) -- fetched lazily, only
    # for schools that actually need plotting (pipeline schools), not
    # backfilled for the whole 25k-school registry up front.
    latitude: Mapped[float | None] = mapped_column(Float, nullable=True)
    longitude: Mapped[float | None] = mapped_column(Float, nullable=True)

    raw_import_row: Mapped[dict] = mapped_column(JSON, nullable=False)

    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, index=True)
    first_imported_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    last_seen_in_import_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    last_import_batch_id: Mapped[int | None] = mapped_column(ForeignKey("import_batches.id"), nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())


# What counts as a school this tool works with, applied by EVERY listing,
# count, facet, search, summary, and the auto-enrich picker: active in the
# register, not an adult-education program, not a dedicated special-needs
# institution. The latter two are eliminated outright (owner's call: never
# targets for a kids' English program), not filterable -- the rows stay in
# the database untouched so nothing is destroyed, but no surface shows them.
# A school that enrichment later tags with a specialty drops out the same
# way. Lives here (not in the API layer) because services need it too.
TARGET_SCHOOL_CONDITIONS = (
    School.is_active.is_(True),
    School.is_adult_education.is_(False),
    School.specialty.is_(None),
)
