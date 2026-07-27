"""CLI: import the RSPO/SIO bulk CSV export into `schools`.

Usage: python -m levelup.cli.import_csv [--csv-path PATH]
"""

from __future__ import annotations

import hashlib
from pathlib import Path

import pandas as pd
import typer

from levelup.core.config import DATA_DIR
from levelup.core.db import SessionLocal
from levelup.models.import_batch import ImportBatch
from levelup.services.import_service.upsert import run_import

SOURCE_URL = (
    "https://api.dane.gov.pl/resources/1254769,"
    "wykaz-szko-i-placowek-oswiatowych-wg-stanu-bazy-sio-na-30092025/csv"
)
DEFAULT_CSV_PATH = DATA_DIR / "imports" / "sio_20250930.csv"

app = typer.Typer()


def _clean_row(row: dict) -> dict:
    # pandas represents a missing cell as float NaN (truthy, breaks `x or default`
    # idioms) rather than None -- normalize once at the loading boundary.
    return {k: (None if isinstance(v, float) and v != v else v) for k, v in row.items()}


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


@app.command()
def main(csv_path: Path = DEFAULT_CSV_PATH) -> None:
    if not csv_path.exists():
        raise typer.BadParameter(
            f"{csv_path} not found. Run scripts/inspect_sio_csv.py first to download it."
        )

    df = pd.read_csv(csv_path, encoding="utf-8-sig", dtype=str, low_memory=False)
    rows = [_clean_row(r) for r in df.to_dict(orient="records")]

    session = SessionLocal()
    try:
        batch = ImportBatch(
            source_label="dane.gov.pl SIO 30.09.2025",
            source_url=SOURCE_URL,
            file_sha256=_sha256(csv_path),
            status="running",
        )
        session.add(batch)
        session.flush()

        batch, error_samples = run_import(session, rows, batch)
        session.commit()

        typer.echo(f"Import batch #{batch.id} complete:")
        typer.echo(f"  total rows read:          {batch.row_count_total}")
        typer.echo(f"  imported (upserted):      {batch.row_count_imported}")
        typer.echo(f"  excluded (other type):    {batch.row_count_excluded_other_type}")
        typer.echo(f"  excluded (adult ed):      {batch.row_count_excluded_adult}")
        typer.echo(f"  excluded (special needs): {batch.row_count_excluded_special_needs}")
        typer.echo(f"  excluded (0/blank count): {batch.row_count_excluded_zero_students}")
        typer.echo(f"  errors:                   {batch.row_count_errors}")
        if error_samples:
            typer.echo("\n  sample errors:")
            for msg in error_samples:
                typer.echo(f"    - {msg}")
    finally:
        session.close()


if __name__ == "__main__":
    app()
