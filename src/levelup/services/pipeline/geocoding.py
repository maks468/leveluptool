"""Backfills lat/lng for schools that need plotting on the Pipeline map.

Deliberately lazy and scoped to whichever schools are asked for (pipeline
schools, in practice) rather than the whole 25k-school registry -- most
schools never need a coordinate at all. RSPO's detail API is fast and
unrate-limited at a modest concurrency (confirmed directly while building
the director-name backfill), so this runs inline, on demand, rather than
needing its own background job.
"""

from __future__ import annotations

import concurrent.futures

from sqlalchemy.orm import Session

from levelup.models.school import School
from levelup.services.enrichment.rspo_detail import fetch_rspo_detail, parse_director_and_contacts

MAX_WORKERS = 8


def backfill_missing_coordinates(session: Session, schools: list[School]) -> int:
    targets = [s for s in schools if (s.latitude is None or s.longitude is None) and s.rspo_id]
    if not targets:
        return 0

    def fetch_one(school: School):
        detail = fetch_rspo_detail(school.rspo_id)
        return school, parse_director_and_contacts(detail) if detail else None

    updated = 0
    with concurrent.futures.ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        for school, info in executor.map(fetch_one, targets):
            if info and info.get("latitude") is not None and info.get("longitude") is not None:
                school.latitude = info["latitude"]
                school.longitude = info["longitude"]
                updated += 1
    if updated:
        session.commit()
    return updated
