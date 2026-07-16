"""CLI: fetch + parse the current Perspektywy rankings, match them
against schools, and rescore. Idempotent -- re-running with an unchanged
PDF (same sha256) skips re-parsing but still re-matches/rescore is safe to
run repeatedly.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

import requests
import typer

from levelup.core.config import DATA_DIR
from levelup.core.db import SessionLocal
from levelup.models.ranking import RankingCache, RankingEntry
from levelup.services.ranking import school_matcher
from levelup.services.ranking.perspektywy_parser import parse_pdf
from levelup.services.scoring.rescore import rescore_all

RANKING_YEAR = 2026
SOURCES = {
    "perspektywy_licea": "https://licea.perspektywy.pl/pdf/ranking-licea-2026.pdf",
    "perspektywy_technika": "https://technika.perspektywy.pl/pdf/ranking-technika-2026.pdf",
}
RANKINGS_DIR = DATA_DIR / "rankings"

app = typer.Typer()


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _download(source: str, url: str) -> Path:
    dest = RANKINGS_DIR / f"{source}_{RANKING_YEAR}.pdf"
    if not dest.exists():
        resp = requests.get(url, timeout=60, headers={"User-Agent": "Mozilla/5.0"})
        resp.raise_for_status()
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(resp.content)
    return dest


@app.command()
def main() -> None:
    session = SessionLocal()
    try:
        for source, url in SOURCES.items():
            pdf_path = _download(source, url)
            sha = _sha256(pdf_path)

            existing = (
                session.query(RankingCache)
                .filter_by(source=source, ranking_year=RANKING_YEAR, source_pdf_sha256=sha)
                .one_or_none()
            )
            if existing:
                typer.echo(f"{source}: unchanged since last parse (cache #{existing.id}), skipping re-parse")
                cache = existing
            else:
                parsed = parse_pdf(pdf_path)
                cache = RankingCache(
                    source=source,
                    ranking_year=RANKING_YEAR,
                    source_pdf_path=str(pdf_path),
                    source_pdf_sha256=sha,
                )
                session.add(cache)
                session.flush()

                entries = [
                    RankingEntry(
                        ranking_cache_id=cache.id,
                        rank=e["rank"],
                        school_name_raw=e["name"],
                        city_raw=e["city"],
                        voivodeship_raw=e["voivodeship"],
                        extra={"is_tie": e["is_tie"], "score": e["score"]},
                    )
                    for e in parsed
                ]
                session.add_all(entries)
                session.flush()
                typer.echo(f"{source}: parsed {len(entries)} entries into cache #{cache.id}")

            entries = session.query(RankingEntry).filter_by(ranking_cache_id=cache.id).all()
            match_counts = school_matcher.match_entries(session, entries, source, RANKING_YEAR)
            session.commit()
            typer.echo(f"{source}: matches -> {match_counts}")

        rescore_counts = rescore_all(session)
        typer.echo(f"Rescored after ranking refresh: {rescore_counts}")
    finally:
        session.close()


if __name__ == "__main__":
    app()
