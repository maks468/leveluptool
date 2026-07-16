"""Fuzzy-matches parsed Perspektywy ranking entries against `schools` by
name+city+voivodeship. Only high-confidence matches are auto-confirmed;
everything else is stored as 'auto' (unconfirmed) and contributes nothing
to scoring until a human confirms it -- consistent with "no guessing."
"""

from __future__ import annotations

import re
import unicodedata
from collections import defaultdict

from rapidfuzz import fuzz
from sqlalchemy.orm import Session

from levelup.models.ranking import RankingEntry, SchoolRankingMatch
from levelup.models.school import School, SchoolLevel

CONFIRM_THRESHOLD = 90
DISCARD_BELOW = 80

_ABBREVIATIONS = [
    (re.compile(r"\bLO\b"), "LICEUM OGOLNOKSZTALCACE"),
    (re.compile(r"\bIM\.\s*"), ""),
    (re.compile(r"\bODDZ\.\s*"), "ODDZIALAMI "),
    (re.compile(r"\bDWUJEZ\.\s*"), "DWUJEZYCZNYMI"),
    (re.compile(r"\bMIEDZYNAR\.\s*"), "MIEDZYNARODOWYMI"),
    (re.compile(r"\bNR\.\s*"), "NR "),
]

_DIACRITICS = str.maketrans(
    "ąćęłńóśźżĄĆĘŁŃÓŚŹŻ",
    "acelnoszzACELNOSZZ",
)


def _strip_diacritics(text: str) -> str:
    text = text.translate(_DIACRITICS)
    return unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()


def normalize_name(name: str) -> str:
    n = _strip_diacritics(name.upper())
    for pattern, repl in _ABBREVIATIONS:
        n = pattern.sub(repl, n)
    n = re.sub(r"[^A-Z0-9 ]", " ", n)
    return re.sub(r"\s+", " ", n).strip()


def normalize_city(city: str) -> str:
    return _strip_diacritics(city.upper()).strip()


LEVEL_BY_SOURCE = {
    "perspektywy_licea": SchoolLevel.LICEUM,
    "perspektywy_technika": SchoolLevel.TECHNIKUM,
}


def match_entries(session: Session, entries: list[RankingEntry], source: str, ranking_year: int) -> dict[str, int]:
    level = LEVEL_BY_SOURCE[source]
    schools = session.query(School).filter(School.level == level, School.is_active.is_(True)).all()

    candidates_by_city: dict[str, list[School]] = defaultdict(list)
    for sch in schools:
        if sch.city:
            candidates_by_city[normalize_city(sch.city)].append(sch)

    counts = {"confirmed": 0, "auto": 0, "discarded": 0}

    for entry in entries:
        candidates = candidates_by_city.get(normalize_city(entry.city_raw), [])
        if not candidates:
            counts["discarded"] += 1
            continue

        norm_entry_name = normalize_name(entry.school_name_raw)
        best_school, best_score = None, 0.0
        for sch in candidates:
            score = fuzz.token_sort_ratio(norm_entry_name, normalize_name(sch.name))
            if score > best_score:
                best_school, best_score = sch, score

        if best_school is None or best_score < DISCARD_BELOW:
            counts["discarded"] += 1
            continue

        status = "confirmed" if best_score >= CONFIRM_THRESHOLD else "auto"
        session.add(
            SchoolRankingMatch(
                school_id=best_school.id,
                ranking_entry_id=entry.id,
                ranking_year=ranking_year,
                match_confidence=best_score / 100,
                match_status=status,
            )
        )
        counts[status] += 1

    return counts
