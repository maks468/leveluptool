"""Step 0: download the RSPO/SIO bulk export and report its real structure.

Nothing in the import pipeline gets written until this has been run and its
output reviewed — column names, encoding, and enum-ish values below are
assumptions until confirmed here.
"""

from __future__ import annotations

import sys
from pathlib import Path

import requests

SOURCE_URL = (
    "https://api.dane.gov.pl/resources/1254769,"
    "wykaz-szko-i-placowek-oswiatowych-wg-stanu-bazy-sio-na-30092025/csv"
)
DEST = Path(__file__).resolve().parent.parent / "data" / "imports" / "sio_20250930.csv"

CANDIDATE_ENCODINGS = ["utf-8-sig", "utf-8", "cp1250", "iso-8859-2"]


def download() -> Path:
    if DEST.exists():
        print(f"Already downloaded: {DEST} ({DEST.stat().st_size:,} bytes)")
        return DEST
    print(f"Downloading {SOURCE_URL} ...")
    resp = requests.get(SOURCE_URL, timeout=120)
    resp.raise_for_status()
    DEST.parent.mkdir(parents=True, exist_ok=True)
    DEST.write_bytes(resp.content)
    print(f"Saved {DEST} ({len(resp.content):,} bytes)")
    return DEST


def detect_encoding(path: Path) -> str:
    raw = path.read_bytes()[:200_000]
    for enc in CANDIDATE_ENCODINGS:
        try:
            raw.decode(enc)
            return enc
        except UnicodeDecodeError:
            continue
    raise RuntimeError("Could not detect encoding among candidates")


def main() -> None:
    path = download()
    encoding = detect_encoding(path)
    print(f"\nDetected encoding: {encoding}")

    import pandas as pd

    # Sniff the delimiter — Polish gov CSVs are frequently semicolon-delimited.
    with open(path, "r", encoding=encoding, errors="strict") as f:
        header_line = f.readline()
    delimiter = ";" if header_line.count(";") > header_line.count(",") else ","
    print(f"Detected delimiter: {delimiter!r}")

    df = pd.read_csv(path, encoding=encoding, sep=delimiter, dtype=str, low_memory=False)
    print(f"\nRow count: {len(df):,}")
    print(f"Column count: {len(df.columns)}")
    print("\n--- Columns ---")
    for col in df.columns:
        print(f"  {col!r}")

    print("\n--- Sample values per column (first 5 non-null, unique) ---")
    for col in df.columns:
        uniques = df[col].dropna().unique()[:5]
        print(f"\n{col!r}:")
        for v in uniques:
            print(f"    {v!r}")

    print("\n--- Distinct-value counts for likely enum columns (<=60 uniques) ---")
    for col in df.columns:
        n_unique = df[col].nunique(dropna=True)
        if 0 < n_unique <= 60:
            print(f"\n{col!r} ({n_unique} distinct values):")
            print(df[col].value_counts(dropna=False).head(60).to_string())

    out_path = path.parent / "column_report.txt"
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(f"encoding={encoding}\ndelimiter={delimiter}\nrows={len(df)}\n\n")
        f.write("columns:\n")
        for col in df.columns:
            f.write(f"  {col}\n")
    print(f"\nWrote summary to {out_path}")


if __name__ == "__main__":
    sys.exit(main())
