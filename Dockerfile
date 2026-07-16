# syntax=docker/dockerfile:1

# ---------- stage 1: build the frontend to static files ----------
FROM node:22-slim AS frontend
WORKDIR /app/frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build          # -> /app/frontend/dist

# ---------- stage 2: backend runtime ----------
FROM python:3.12-slim AS runtime
ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    LEVELUP_FRONTEND_DIST=/app/frontend/dist
WORKDIR /app

# The package MUST be installed editable with the repo layout in place:
# core/config.py derives PROJECT_ROOT (and thus data/ + config/) from the
# source file location, so `levelup` has to live at /app/src/levelup.
COPY pyproject.toml README.md ./
COPY src/ ./src/
# Python deps + Playwright's Chromium and the OS libraries it needs
# (--with-deps installs them via apt). This is the bulk of the image; it's
# what lets enrichment read JS-rendered / anti-bot school sites.
RUN pip install -e "." && python -m playwright install --with-deps chromium

# Runtime files. config/ is also a bind-mount in compose (so rubric edits
# persist and are editable live); this COPY is just a sensible default when
# no mount is provided.
COPY alembic.ini ./
COPY migrations/ ./migrations/
COPY config/ ./config/
COPY scripts/ ./scripts/

# Built SPA from stage 1 -- FastAPI serves it same-origin (see main.py).
COPY --from=frontend /app/frontend/dist ./frontend/dist

# Seed library baked in at a NON-mounted path so bootstrap_db.py can restore
# the pre-loaded RSPO library on first run even if the data volume is empty
# (it also finds it via the repo/volume at data/seed/).
COPY data/seed/ /app/seed/
ENV LEVELUP_SEED_PATH=/app/seed/levelup_seed.db.gz

# data/ (SQLite DB + caches + imports = the entire app state) is a
# persistent volume mounted by compose; make sure the dir exists.
RUN mkdir -p /app/data

EXPOSE 8322

# Restore the seed library on first run, migrate to head, then serve. ONE
# worker on purpose: the auto-enrich background thread and SQLite's
# single-writer model both assume a single process -- do NOT scale this
# with --workers.
CMD ["sh", "-c", "python scripts/bootstrap_db.py && python -m alembic upgrade head && python -m uvicorn levelup.main:app --host 0.0.0.0 --port 8322 --workers 1"]
