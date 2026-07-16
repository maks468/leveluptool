"""First-run database bootstrap.

Restores the shipped RSPO seed library (data/seed/levelup_seed.db.gz) into
data/levelup.db when no database exists yet -- so a fresh clone or a new
deployment comes up with the full ~25k-school library already loaded and
scored, no import step required. The seed is a privacy-safe *clean slate*:
public RSPO register data + scores only, with no scraped contacts, no
pipeline, and no activity.

Idempotent: if data/levelup.db already exists, this does nothing (your live
data is never overwritten). If the seed is missing too, it leaves things to
`alembic upgrade head`, which creates an empty database.
"""

from __future__ import annotations

import gzip
import os
import shutil
from pathlib import Path

from levelup.core.config import DATA_DIR

DB_PATH = DATA_DIR / "levelup.db"

# Look for the seed in the repo/volume first (data/seed/), then at a baked
# image path (LEVELUP_SEED_PATH, set by the Dockerfile) so the container is
# self-contained even when run without the data volume mounted.
_SEED_CANDIDATES = [
    DATA_DIR / "seed" / "levelup_seed.db.gz",
    Path(os.environ["LEVELUP_SEED_PATH"]) if os.environ.get("LEVELUP_SEED_PATH") else None,
]


def _find_seed() -> Path | None:
    for p in _SEED_CANDIDATES:
        if p and p.exists():
            return p
    return None


def main() -> None:
    if DB_PATH.exists():
        print(f"[bootstrap] {DB_PATH} already exists -- leaving it untouched.")
        return
    seed = _find_seed()
    if seed is None:
        print("[bootstrap] no seed found -- an empty DB will be created by migrations.")
        return
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(seed, "rb") as src, open(DB_PATH, "wb") as dst:
        shutil.copyfileobj(src, dst)
    print(f"[bootstrap] restored seed library from {seed} -> {DB_PATH}")


if __name__ == "__main__":
    main()
