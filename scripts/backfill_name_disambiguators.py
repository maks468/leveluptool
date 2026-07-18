"""Backfill School.name_disambiguator for schools whose official name + city
is NOT unique (e.g. the several "BRANŻOWA SZKOŁA I STOPNIA W RADOMIU", each in
a different Zespół). Uses the parent complex (Zespół) from the RSPO API to
tell them apart; falls back to "RSPO <id>" when the complex can't (schools in
the same complex, or no complex on record). Schools whose name+city is already
unique are left NULL.

Idempotent -- clears stale values and recomputes, so it's safe to re-run after
a fresh RSPO import.
"""

from __future__ import annotations

import re
from collections import defaultdict

from levelup.core.db import SessionLocal
from levelup.models.school import School
from levelup.services.enrichment.rspo_detail import fetch_rspo_detail

_DIACRITICS = str.maketrans("ąćęłńóśźżĄĆĘŁŃÓŚŹŻ", "acelnoszzACELNOSZZ")
_LOWERCASE_WORDS = {"i", "z", "ze", "w", "we", "nr", "dla", "oraz", "na", "do", "przy", "im."}


def _stem(word: str) -> str:
    return word.translate(_DIACRITICS).lower()[:4]


def _titlecase(text: str) -> str:
    return " ".join(
        w if w in _LOWERCASE_WORDS else (w[:1].upper() + w[1:]) for w in text.lower().split()
    )


def _clean_parent(raw: str | None, city: str | None) -> str | None:
    """Turn "ZESPÓŁ SZKÓŁ BUDOWLANYCH IM. KAZIMIERZA WIELKIEGO W RADOMIU"
    into "Zespół Szkół Budowlanych" -- drop the patron ("im. ...") and the
    redundant trailing city clause, then title-case."""
    if not raw:
        return None
    name = re.split(r"\s+im\.\s+", raw.strip(), maxsplit=1, flags=re.IGNORECASE)[0].strip()
    m = re.match(r"^(.*)\s+we?\s+(\S.*)$", name, flags=re.IGNORECASE)
    if m and city and _stem(m.group(2).split()[0]) == _stem(city.split()[0]):
        name = m.group(1).strip()
    return _titlecase(name) or None


def main() -> None:
    session = SessionLocal()
    schools = session.query(School).filter(School.is_active.is_(True)).all()

    groups: dict[tuple[str, str], list[School]] = defaultdict(list)
    for sc in schools:
        groups[(sc.name.strip().lower(), (sc.city or "").strip().lower())].append(sc)
    dup_groups = {k: v for k, v in groups.items() if len(v) > 1}
    dup_ids = {sc.id for members in dup_groups.values() for sc in members}
    print(f"duplicate name+city groups: {len(dup_groups)} | schools in them: {len(dup_ids)}")

    changed = 0
    # 1) clear stale values on schools that are no longer duplicates
    for sc in schools:
        if sc.id not in dup_ids and sc.name_disambiguator is not None:
            sc.name_disambiguator = None
            changed += 1

    # 2) assign a unique disambiguator within each duplicate group
    for members in dup_groups.values():
        parent = {}
        for sc in members:
            detail = fetch_rspo_detail(sc.rspo_id) if sc.rspo_id else None
            parent[sc.id] = _clean_parent(((detail or {}).get("parentInstitution") or {}).get("name"), sc.city)
        counts: dict[str, int] = defaultdict(int)
        for name in parent.values():
            if name:
                counts[name] += 1
        for sc in members:
            pname = parent[sc.id]
            if pname and counts[pname] == 1:
                disamb = pname
            elif pname:
                disamb = f"{pname} · RSPO {sc.rspo_id}"  # shared complex -> add id to stay unique
            else:
                disamb = f"RSPO {sc.rspo_id}"
            if sc.name_disambiguator != disamb:
                sc.name_disambiguator = disamb
                changed += 1

    session.commit()
    print(f"updated {changed} rows")
    example = next(iter(dup_groups.values()), [])
    for sc in example:
        print(f"   {sc.rspo_id}: {sc.name[:38]} -> {sc.name_disambiguator!r}")


if __name__ == "__main__":
    main()
