"""Maps a raw SIO/RSPO CSV row (as produced by the 30.09.2025 dane.gov.pl
export inspected via scripts/inspect_sio_csv.py) to School model kwargs.

Grounded in the real column names/values found in that export — see
data/imports/column_report.txt for the full inspection output. Do not
adjust these mappings without re-inspecting a real export first.
"""

from __future__ import annotations

import re

from levelup.models.school import EvidenceSource, LanguageOrientation, OwnershipSubtype, SchoolLevel

TARGET_TYPE_MAP: dict[str, SchoolLevel] = {
    "Szkoła podstawowa": SchoolLevel.PRIMARY,
    "Liceum ogólnokształcące": SchoolLevel.LICEUM,
    "Technikum": SchoolLevel.TECHNIKUM,
    "Branżowa szkoła I stopnia": SchoolLevel.BRANZOWA_I,
    "Branżowa szkoła II stopnia": SchoolLevel.BRANZOWA_II,
    "Szkoła policealna": SchoolLevel.POLICEALNA,
}

BRANCH_KIND = "filia szkoły lub placówki"
ADULT_CATEGORY = "Dorośli"

_BILINGUAL_RE = re.compile(r"DWUJ", re.IGNORECASE)
_INTERNATIONAL_RE = re.compile(r"MIĘDZYNARODOW|INTERNATIONAL", re.IGNORECASE)
_SPOLECZNA_FALSE_POSITIVES = ("POMOCY SPOŁECZ", "DOMU POMOCY")

_SINGLE_CITY_GMINA = "M"  # RSPO's "Typ gminy" code for a single-city urban commune
_GMINA_CITY_PREFIX_RE = re.compile(r"^M\.\s*(st\.\s*)?", re.IGNORECASE)


def is_adult_education(row: dict) -> bool:
    return row.get("Kategoria uczniów") == ADULT_CATEGORY


def _normalize_city(row: dict) -> str | None:
    """RSPO's "Miejscowość" field is split into individual districts for
    several big cities (e.g. Warsaw's Mokotów/Wola/..., Kraków's -Podgórze/
    -Śródmieście/...) while "Gmina" always carries the single real city name
    whenever "Typ gminy" says the commune is a pure single-city ("M") one --
    verified structurally from those two fields, not guessed from a
    hardcoded district list (which risks missing districts, or wrongly
    matching an unrelated village that happens to share a district's name,
    e.g. "Wola" is also a real village elsewhere in Poland)."""
    if row.get("Typ gminy") == _SINGLE_CITY_GMINA:
        gmina = (row.get("Gmina") or "").strip()
        if gmina:
            return _GMINA_CITY_PREFIX_RE.sub("", gmina).strip()
    return row.get("Miejscowość") or None


def _detect_ownership_subtype(name: str) -> tuple[OwnershipSubtype, bool, EvidenceSource]:
    """A private school is, by RSPO's own "Publiczność" field, literally
    "niepubliczna" -- that's not a guess, it's the same source fact that set
    is_private=True. społeczna/międzynarodowa are extra designations some
    niepubliczna schools additionally carry, detected here from the name;
    absent one of those, niepubliczna itself is the verified subtype."""
    upper = name.upper()
    if _INTERNATIONAL_RE.search(upper):
        return OwnershipSubtype.MIEDZYNARODOWA, True, EvidenceSource.RSPO_NAME_MATCH
    if "SPOŁECZ" in upper and not any(fp in upper for fp in _SPOLECZNA_FALSE_POSITIVES):
        return OwnershipSubtype.SPOLECZNA, True, EvidenceSource.RSPO_NAME_MATCH
    return OwnershipSubtype.NIEPUBLICZNA, True, EvidenceSource.RSPO_STRUCTURED_FIELD


def _detect_language_orientation(name: str) -> tuple[LanguageOrientation | None, EvidenceSource | None]:
    if _BILINGUAL_RE.search(name.upper()):
        return LanguageOrientation.BILINGUAL, EvidenceSource.RSPO_NAME_MATCH
    # Middle/lower tiers (English-first-plus-extra vs standard-English-only)
    # aren't verifiable from RSPO at all -- left blank pending enrichment.
    return None, None


def _parse_student_count(raw: str | None) -> int | None:
    if raw is None or raw == "" or raw.lower() == "nan":
        return None
    try:
        return int(float(raw))
    except ValueError:
        return None


def map_row(row: dict) -> dict:
    """Row must already have passed exclusion_rules.should_import()."""
    name = row["Nazwa placówki"]
    level = TARGET_TYPE_MAP[row["Typ podmiotu"]]

    publicznosc = (row.get("Publiczność") or "").strip().lower()
    is_private = publicznosc.startswith("niepubliczna") if publicznosc else None

    ownership_subtype = ownership_verified = ownership_source = None
    if is_private:
        ownership_subtype, ownership_verified, ownership_source = _detect_ownership_subtype(name)
        ownership_verified = bool(ownership_verified)

    language_orientation, language_source = _detect_language_orientation(name)

    is_branch = (row.get("Rodzaj szkoły/placówki") or "").strip() == BRANCH_KIND
    has_grades_7_8 = (not is_branch) if level == SchoolLevel.PRIMARY else None

    return dict(
        rspo_id=row["RSPO"],
        name=name,
        level=level,
        voivodeship=row.get("Wojewodztwo") or None,
        city=_normalize_city(row),
        is_private=is_private,
        ownership_subtype=ownership_subtype,
        ownership_subtype_verified=bool(ownership_verified),
        ownership_subtype_source=ownership_source,
        student_count=_parse_student_count(row.get("ucz_ogolem")),
        is_adult_education=is_adult_education(row),
        is_branch=is_branch,
        has_grades_7_8=has_grades_7_8,
        website_url=(row.get("Adres www") or None),
        language_orientation=language_orientation,
        language_orientation_source=language_source,
        raw_import_row=row,
    )
