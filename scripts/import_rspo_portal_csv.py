"""Import an RSPO-portal CSV export (semicolon-delimited, rspo.gov.pl download)
by adapting its columns to the SIO-export names the import pipeline expects,
then running the SAME run_import() as levelup.cli.import_csv — identical
exclusion rules (target types only, no adult-ed / special-needs / zero-student
rows) and idempotent RSPO-keyed upsert.

Column equivalences verified against a real export on 2026-08-03
(see the profile in that day's session): every consumed field has a direct
counterpart; two are synthesized:
  - "Czy szkoła": the portal export has no such flag; set to "1" — the
    TARGET_TYPE_MAP check is what actually filters school types, and no
    non-school facility type collides with those names.
  - "Typ gminy": derived from the TERYT gmina code's 7th digit
    (1 == gmina miejska == the old export's "M"), which is the same fact
    _normalize_city() used to pick the real city name over a district name.
    District rows (type digit 8 == dzielnica m.st. Warszawy, 9 == delegatura
    in Kraków/Łódź/Poznań/Wrocław) carry the DISTRICT in both "Miejscowość"
    and "Gmina" — there the real city lives in "Powiat" (these five cities
    are miasta na prawach powiatu), so "Gmina" is overwritten with it and
    the row is flagged "M" for _normalize_city() to pick up.

Usage (inside the app container):
    python scripts/import_rspo_portal_csv.py /app/data/imports/rspo_2026_08_03.csv
"""

from __future__ import annotations

import hashlib
import re
import sys
from pathlib import Path

import pandas as pd

from levelup.core.db import SessionLocal
from levelup.models.import_batch import ImportBatch
from levelup.services.import_service.upsert import run_import

# portal-export column -> SIO-export column consumed by the pipeline
RENAMES = {
    "Numer RSPO": "RSPO",
    "Typ": "Typ podmiotu",
    "Nazwa": "Nazwa placówki",
    "Województwo": "Wojewodztwo",  # old export header carries no diacritics
    "Publiczność status": "Publiczność",
    "Specyfika placówki": "Specyfika szkoły",
    "Miejsce w strukturze": "Rodzaj szkoły/placówki",
    "Liczba uczniów": "ucz_ogolem",
    "Strona www": "Adres www",
}
# "Miejscowość", "Gmina", "Kategoria uczniów" already share their names.

_EXCEL_WRAP_RE = re.compile(r'^="(.*)"$')
_URBAN_GMINA_TERYT_TYPE = "1"  # 7th TERYT digit: 1 == gmina miejska
_DISTRICT_TERYT_TYPES = ("8", "9")  # 8 == dzielnica m.st. Warszawy, 9 == delegatura


def _unwrap(value):
    """Strip the ="..." Excel-guard wrapper the portal puts on code fields."""
    if isinstance(value, str):
        m = _EXCEL_WRAP_RE.match(value)
        if m:
            return m.group(1)
    return value


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def convert(df: pd.DataFrame) -> list[dict]:
    df = df.map(_unwrap)
    df = df.rename(columns=RENAMES)

    codes = (
        df["Kod terytorialny gmina"] if "Kod terytorialny gmina" in df.columns
        else pd.Series([""] * len(df), index=df.index)
    )
    typ_gminy = []
    gmina_fixed = []
    for code, gmina, powiat in zip(codes, df["Gmina"], df["Powiat"]):
        digit = code[6] if isinstance(code, str) and len(code) >= 7 else ""
        if digit == _URBAN_GMINA_TERYT_TYPE:
            typ_gminy.append("M")
            gmina_fixed.append(gmina)
        elif digit in _DISTRICT_TERYT_TYPES:
            # district row: Gmina holds the district; the city is the Powiat
            typ_gminy.append("M")
            gmina_fixed.append(powiat)
        else:
            typ_gminy.append("")
            gmina_fixed.append(gmina)
    df["Typ gminy"] = typ_gminy
    df["Gmina"] = gmina_fixed
    df["Czy szkoła"] = "1"

    rows = df.to_dict(orient="records")
    # NaN -> None at the loading boundary, same as levelup.cli.import_csv
    return [
        {k: (None if isinstance(v, float) and v != v else v) for k, v in row.items()}
        for row in rows
    ]


def main() -> None:
    if len(sys.argv) != 2:
        raise SystemExit("usage: import_rspo_portal_csv.py <path-to-portal-export.csv>")
    csv_path = Path(sys.argv[1])
    if not csv_path.exists():
        raise SystemExit(f"{csv_path} not found")

    df = pd.read_csv(csv_path, sep=";", encoding="utf-8-sig", dtype=str, low_memory=False)
    missing = [c for c in RENAMES if c not in df.columns]
    if missing:
        raise SystemExit(f"not an RSPO portal export — missing columns: {missing}")

    liquidated = df["Data likwidacji"].notna().sum() if "Data likwidacji" in df.columns else 0
    if liquidated:
        df = df[df["Data likwidacji"].isna()]
        print(f"dropped {liquidated} liquidated rows (Data likwidacji set)")

    rows = convert(df)

    session = SessionLocal()
    try:
        batch = ImportBatch(
            source_label=f"RSPO portal export ({csv_path.name})",
            source_url="https://rspo.gov.pl/",
            file_sha256=_sha256(csv_path),
            status="running",
        )
        session.add(batch)
        session.flush()

        batch, error_samples = run_import(session, rows, batch)
        session.commit()

        print(f"Import batch #{batch.id} complete:")
        print(f"  total rows read:          {batch.row_count_total}")
        print(f"  imported (upserted):      {batch.row_count_imported}")
        print(f"  excluded (other type):    {batch.row_count_excluded_other_type}")
        print(f"  excluded (adult ed):      {batch.row_count_excluded_adult}")
        print(f"  excluded (special needs): {batch.row_count_excluded_special_needs}")
        print(f"  excluded (0/blank count): {batch.row_count_excluded_zero_students}")
        print(f"  errors:                   {batch.row_count_errors}")
        for msg in error_samples or []:
            print(f"    - {msg}")
    finally:
        session.close()


if __name__ == "__main__":
    main()
