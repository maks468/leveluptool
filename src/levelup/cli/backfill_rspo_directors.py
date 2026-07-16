"""CLI: backfill director names (and registry email/phone) for every school
from RSPO's own live detail API -- authoritative, no website scraping
needed. Confirmed reachable and fast (~50ms/request, no rate limiting
observed at 8 concurrent workers) directly against the real API, unlike
rspo.gov.pl's HTML search frontend which is geo-blocked to Poland.

Only touches schools that don't already have a director_name, so it's
safe to re-run (e.g. after a fresh CSV import adds new schools) without
re-fetching everything.

Usage: python -m levelup.cli.backfill_rspo_directors [--workers 8] [--limit N]
"""

from __future__ import annotations

import concurrent.futures

import typer

from levelup.core.db import SessionLocal
from levelup.models.enrichment import SchoolContact
from levelup.models.school import School
from levelup.services.enrichment.jobs import RSPO_SOURCE_URL_PREFIX
from levelup.services.enrichment.rspo_detail import fetch_rspo_detail, parse_director_and_contacts

app = typer.Typer()


@app.command()
def main(
    workers: int = typer.Option(8, help="Concurrent requests against rspo.gov.pl"),
    limit: int | None = typer.Option(None, help="Cap how many schools to process this run"),
) -> None:
    session = SessionLocal()
    try:
        query = session.query(School.id, School.rspo_id).filter(
            School.is_active.is_(True),
            School.director_name.is_(None),
            School.rspo_id.isnot(None),
        )
        if limit:
            query = query.limit(limit)
        targets = query.all()
        typer.echo(f"Backfilling director names for {len(targets)} schools without one...")

        found = 0
        checked = 0

        def fetch_one(row):
            school_id, rspo_id = row
            detail = fetch_rspo_detail(rspo_id)
            return school_id, rspo_id, parse_director_and_contacts(detail) if detail else None

        with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as executor:
            for school_id, rspo_id, info in executor.map(fetch_one, targets):
                checked += 1
                if info and info.get("director_name"):
                    school = session.query(School).filter_by(id=school_id).one()
                    school.director_name = info["director_name"]
                    session.add(
                        SchoolContact(
                            school_id=school_id,
                            contact_type="director",
                            person_name=info["director_name"],
                            email=info.get("email"),
                            phone=info.get("phone"),
                            source_url=f"{RSPO_SOURCE_URL_PREFIX}{rspo_id}",
                            verified=True,
                        )
                    )
                    found += 1
                if checked % 500 == 0:
                    session.commit()
                    typer.echo(f"  {checked}/{len(targets)} checked, {found} directors found so far")

        session.commit()
        typer.echo(f"Done: {found}/{len(targets)} schools got a director name from RSPO ({found / len(targets) * 100:.1f}%).")
    finally:
        session.close()


if __name__ == "__main__":
    app()
