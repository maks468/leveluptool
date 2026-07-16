"""Parses a Perspektywy ranking PDF (licea or technika) into rank/name/
city/voivodeship rows.

Verified against the 2026 PDF layout (licea.perspektywy.pl/pdf/ranking-
licea-2026.pdf, technika.perspektywy.pl/pdf/ranking-technika-2026.pdf):
each table row is [<rank>, <name>, <city>, <voivodeship>, <3 sub-rank
ints>, <score>, <3 or 4 pct columns>], sometimes prefixed by an extra
vertical sidebar-marker cell that shifts every column right by one. We
locate the rank cell dynamically (regex, first two positions) rather than
assuming a fixed column index, so that shift doesn't matter. If a future
year's layout drifts, add a new module here rather than editing this one
blindly -- keep this one as the "2026 layout" parser.
"""

from __future__ import annotations

from pathlib import Path

import pdfplumber

VOIVODESHIPS = {
    "dolnośląskie", "kujawsko-pomorskie", "lubelskie", "lubuskie", "łódzkie",
    "małopolskie", "mazowieckie", "opolskie", "podkarpackie", "podlaskie",
    "pomorskie", "śląskie", "świętokrzyskie", "warmińsko-mazurskie",
    "wielkopolskie", "zachodniopomorskie",
}

_RANK_RE_CACHE = None


def _rank_re():
    global _RANK_RE_CACHE
    if _RANK_RE_CACHE is None:
        import re

        _RANK_RE_CACHE = re.compile(r"^(\d+)(=?)$")
    return _RANK_RE_CACHE


def _decimal_re():
    import re

    return re.compile(r"^\d+,\d+$")


def _find_rank_index(row: list) -> int | None:
    rank_re = _rank_re()
    for i in range(min(2, len(row))):
        cell = row[i]
        if cell and rank_re.match(cell.strip()):
            return i
    return None


def parse_pdf(path: Path) -> list[dict]:
    entries: list[dict] = []
    rank_re = _rank_re()
    decimal_re = _decimal_re()

    seen: set[tuple[int, str, str]] = set()

    with pdfplumber.open(path) as pdf:
        for page in pdf.pages:
            tables = page.extract_tables()
            if not tables:
                continue
            # Some pages get split into multiple table fragments by
            # pdfplumber's line-detection; a row missing identifying cells
            # (rank/name/city/voivodeship) is a mis-sliced fragment of a
            # row that's captured intact in another fragment -- safe to
            # skip rather than reconstruct.
            for table in tables:
                for row in table:
                    if not row:
                        continue
                    idx = _find_rank_index(row)
                    if idx is None:
                        continue
                    try:
                        rank_cell = row[idx].strip()
                        name = row[idx + 1]
                        city = row[idx + 2]
                        voivodeship = row[idx + 3]
                        score_cell = row[idx + 7] if len(row) > idx + 7 else None
                    except IndexError:
                        continue
                    if not name or not city or not voivodeship:
                        continue
                    if voivodeship.strip().lower() not in VOIVODESHIPS:
                        continue  # excludes the header row (rank cell == the report year)

                    match = rank_re.match(rank_cell)
                    dedupe_key = (int(match.group(1)), name.strip().upper(), city.strip().upper())
                    if dedupe_key in seen:
                        continue
                    seen.add(dedupe_key)

                    score = None
                    if score_cell and decimal_re.match(score_cell.strip()):
                        score = float(score_cell.strip().replace(",", "."))

                    entries.append(
                        {
                            "rank": int(match.group(1)),
                            "is_tie": bool(match.group(2)),
                            "name": name.strip(),
                            "city": city.strip(),
                            "voivodeship": voivodeship.strip(),
                            "score": score,
                        }
                    )
    return entries
