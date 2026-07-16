# LevelUp Schools CRM

A CRM-style tool for managing English-language-program outreach to Polish
schools. See `.claude/plans/ticklish-jingling-hoare.md`-style context: this
tool never fabricates data — every field is either verified from RSPO (the
Polish schools register) or a school's own website, or left blank.

Two halves:

- **Library** — the full national register of target-level schools
  (primary/liceum/technikum), auto-scored on import against a config-driven
  rubric.
- **Pipeline** — a standard CRM flow (not_contacted → ... → won/lost) for
  schools you've decided to actively pursue, with an append-only activity
  log and on-demand contact enrichment.

## Quick start (pre-loaded — no import needed)

This repo ships a **seed library**: the full RSPO school register (~25k
schools) already imported and scored, as a privacy-safe *clean slate* —
public register data only, with **no scraped contacts, no pipeline, and no
activity**. On first run the app restores it automatically (via
`scripts/bootstrap_db.py`), so you can open the tool and immediately browse
the library, pull schools into the pipeline, and run enrichment — nothing to
import.

**With Docker (easiest — see [DEPLOY.md](DEPLOY.md) for hosting it for a team):**
```bash
docker compose up --build      # restores the seed, migrates, serves same-origin
```

**Without Docker (local dev):**
```bash
python -m venv .venv
./.venv/Scripts/python.exe -m pip install -e ".[dev]"
./.venv/Scripts/python.exe -m playwright install chromium
./.venv/Scripts/python.exe scripts/bootstrap_db.py     # restores the seed library
./.venv/Scripts/python.exe -m alembic upgrade head
./.venv/Scripts/python.exe -m uvicorn levelup.main:app --port 8322
# frontend, separate terminal:
cd frontend && npm install && npm run dev
```
Open http://localhost:5173 (dev). The sections below ("First-time setup",
"Loading real data") are only needed if you're starting from a *truly empty*
database instead of the shipped seed.

## Stack

- **Backend**: Python 3.12, FastAPI, SQLAlchemy 2.0, SQLite (WAL mode),
  Alembic migrations, Typer CLI commands.
- **Frontend**: React + TypeScript + Vite, Tailwind CSS, TanStack Query/Table,
  dnd-kit, Zustand, React Router.

## First-time setup

```bash
# Backend (Windows paths shown; use .venv/bin/python on macOS/Linux)
python -m venv .venv
./.venv/Scripts/python.exe -m pip install -e ".[dev]"
./.venv/Scripts/python.exe -m alembic upgrade head

# Headless browser used by enrichment to read JS-rendered school sites
# (edupage.org, szkolnastrona.pl, ...). One-time download of the Chromium
# binary; enrichment still runs without it, just skipping those sites.
./.venv/Scripts/python.exe -m playwright install chromium

# Seed the single owner user (id=1) -- required once before anything else works
./.venv/Scripts/python.exe -c "
from levelup.core.db import SessionLocal
from levelup.models import User
s = SessionLocal()
s.add(User(id=1, display_name='Owner', email=None))
s.commit()
"

# Frontend
cd frontend
npm install
```

## Loading real data (run once, then periodically to refresh)

```bash
# 1. Download + inspect the RSPO/SIO bulk export (writes data/imports/sio_20250930.csv)
./.venv/Scripts/python.exe scripts/inspect_sio_csv.py

# 2. Import it (idempotent -- safe to re-run against a newer export later)
./.venv/Scripts/python.exe -m levelup.cli.import_csv

# 3. Score every school against the current rubric config
./.venv/Scripts/python.exe -m levelup.services.scoring.rescore

# 4. Fetch + match the Perspektywy rankings (secondary rubric's ranking criterion)
./.venv/Scripts/python.exe -m levelup.cli.refresh_rankings   # also rescores automatically
```

Re-running the import upserts by RSPO ID and never touches pipeline state,
activity logs, contacts, or scores — only RSPO-sourced columns on `schools`.
A school missing from a newer export is marked `is_active=False`, never
deleted.

## Running the app

Two processes, in separate terminals:

```bash
# Backend (from repo root)
./.venv/Scripts/python.exe -m uvicorn levelup.main:app --port 8322

# Frontend (from frontend/)
npm run dev
```

Open http://localhost:5173 — it proxies `/api` to the backend on port 8322
(see `frontend/vite.config.ts` if you need to change the port).

Note on `--reload`: it's convenient but on this Windows setup a killed
`--reload` process has repeatedly left a phantom entry still "LISTENING" on
its port (visible in `netstat`, but `taskkill` reports the PID doesn't
exist) — the next server then silently fails to bind. If that happens,
just pick a different port rather than fighting it. Restarting the plain
(non-`--reload`) command above after backend changes is the more reliable
default.

## Rubric tuning

All scoring weights live in `config/scoring/primary_rubric.yaml`,
`secondary_rubric.yaml`, and `city_tiers.yaml` — hand-editable, not
hardcoded. After changing a rubric, re-run the rescore command above; it
reads current evidence straight from the database, so **no re-import is
needed** to pick up a weight change.

Known limitation, by design: RSPO's bulk export carries no
curriculum/language-profile field at all. Only the "bilingual" tier of the
language-orientation criterion is verifiable at import (via "z oddziałami
dwujęzycznymi" in a school's official name) — the middle and lower tiers
require on-demand enrichment of the school's own website. A school scores
0/unknown for that criterion until enrichment fills it in; this is the
intended "blank is better than a guess" behavior, not a bug.

## Portability

Everything that makes this installation *this* installation lives under
`data/` (the SQLite DB, downloaded CSV/PDF sources, enrichment cache) and
`config/` (rubric weights). Copy the whole project folder to another
machine, re-run the two "first-time setup" install steps there (dependencies
aren't portable, data is), and it picks up exactly where it left off. Stop
the backend process first — Windows file-locking behaves differently from
Linux if you copy `levelup.db` while it's still open.

## Deferred / architected-for-later

Not built in this pass, but the seams exist so they slot in without a
rewrite:

- **Live RSPO API integration** — the bulk CSV export is used instead
  (gated live API requires a formal ~14-day access request). Swap
  `scripts/inspect_sio_csv.py`'s source in `levelup/cli/import_csv.py`
  when/if that access is granted.
- **Outbound email, open/read tracking, automated reminders** —
  `src/levelup/services/automation/` defines the interfaces
  (`EmailSender`, `ReminderScheduler`, `EventTracker`) with no-op
  implementations wired through `registry.py`. Real implementations plug
  in by editing only that one file.
- **External public API** — the FastAPI layer is already versioned under
  `/api/v1/`, with every route resolved through a single
  `core.security.get_current_user` stub. Opening it up externally later
  means adding real auth/CORS/rate-limiting there, not a redesign.
- **Multi-user** — `owner_id`/`actor_id` foreign keys already exist on
  `pipeline_state`/`activity_log`, defaulted to one seeded `users` row.
