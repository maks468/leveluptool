"""Backfill School.name_disambiguator for schools whose official name + city
is NOT unique (e.g. the several "BRANŻOWA SZKOŁA I STOPNIA W RADOMIU", each in
a different Zespół, or two identically-named "SZKOŁA PODSTAWOWA W KRZESZOWIE"
that turn out to be 300km apart in different voivodeships). Every fallback is
something a human doing outreach would recognize and could act on -- never an
internal id:

  1. the parent complex ("Zespół") name, when it's unique among the duplicates
  2. parent name + street address, when siblings share the same complex
  3. street address alone, when there's no parent complex on record at all
  4. gmina name, only if a school has neither a parent nor a street on record
  5. the school's own director, only for the rare pair that's still identical
     after all of the above (e.g. two parallel RSPO registrations at one site)

Schools whose name+city is already unique are left NULL.

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


def _clean_address(detail: dict) -> str | None:
    """"ul. Betlejemska" + "1" -> "ul. Betlejemska 1" -- the school's own
    street address, always distinct between two separately-run schools even
    when their name, city, and RSPO parent complex all happen to match. Many
    Polish villages have no named streets at all and address by village name
    + plot number instead (e.g. "Jastrzębie 14") -- falls back to that rather
    than emitting a bare, meaningless number on its own."""
    street = (detail.get("hqAddressStreet") or "").strip()
    building = (detail.get("hqAddressBuildingNr") or "").strip()
    if street:
        return f"{street} {building}".strip()
    locality = ((detail.get("hqAddressLocality") or {}).get("name") or "").strip()
    if locality and building:
        return f"{locality} {building}"
    return None


def _clean_commune(detail: dict) -> str | None:
    """Last-resort fallback for the rare school with neither a parent complex
    nor a street on record -- the gmina it belongs to, e.g. "gmina Krzeszów"."""
    commune = ((detail.get("hqAddressLocality") or {}).get("commune") or {}).get("name")
    return f"gmina {commune.strip()}" if commune else None


def _clean_director(detail: dict) -> str | None:
    """Final tie-breaker for the rare pair that's still identical after
    parent/address/commune -- e.g. two parallel RSPO registrations at the
    same site. A named director is a real, actionable fact ("ask for
    Borkowska"), unlike an arbitrary id."""
    surname = (detail.get("directorSurname") or "").strip()
    return surname.title() if surname else None


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
        parent, address, commune, director = {}, {}, {}, {}
        for sc in members:
            detail = fetch_rspo_detail(sc.rspo_id) if sc.rspo_id else None
            detail = detail or {}
            parent[sc.id] = _clean_parent((detail.get("parentInstitution") or {}).get("name"), sc.city)
            address[sc.id] = _clean_address(detail)
            commune[sc.id] = _clean_commune(detail)
            director[sc.id] = _clean_director(detail)
        counts: dict[str, int] = defaultdict(int)
        for name in parent.values():
            if name:
                counts[name] += 1

        disamb_map: dict[int, str | None] = {}
        for sc in members:
            pname, addr, comm = parent[sc.id], address[sc.id], commune[sc.id]
            if pname and counts[pname] == 1:
                disamb_map[sc.id] = pname
            elif pname and addr:
                disamb_map[sc.id] = f"{pname} · {addr}"
            elif addr:
                disamb_map[sc.id] = addr
            elif pname:
                disamb_map[sc.id] = pname
            elif comm:
                disamb_map[sc.id] = comm
            else:
                disamb_map[sc.id] = None

        # still identical for 2+ schools (same complex + same address) ->
        # the director is the last real fact left to tell them apart
        final_counts: dict[str, int] = defaultdict(int)
        for v in disamb_map.values():
            if v:
                final_counts[v] += 1
        for sc in members:
            base = disamb_map[sc.id]
            if base and final_counts[base] > 1 and director[sc.id]:
                disamb_map[sc.id] = f"{base} · Dyr. {director[sc.id]}"

        for sc in members:
            disamb = disamb_map[sc.id]
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
