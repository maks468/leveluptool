# Deploying LevelUp CRM for a small team (always-on)

This runs the whole app as **one container** (FastAPI serves the built
frontend same-origin) behind **Caddy** for HTTPS + a login gate. One shared
dataset, a few gated teammates, always on — independent of your PC.

## What you need
- A small **Linux VM** — 1 vCPU / **2 GB RAM** minimum (Chromium wants the
  headroom), ~10 GB disk. Any provider (Hetzner, DigitalOcean, Vultr, a small
  AWS/GCP instance).
- **Docker + Docker Compose** on it (`curl -fsSL https://get.docker.com | sh`).
- A **domain name** you can point at the VM (needed for automatic HTTPS).

## One-time setup

1. **Copy the project to the VM** — include your existing `data/` and
   `config/` so all the enriched data and rubric weights come with it.
   From your machine (exclude the big local-only dirs):
   ```bash
   rsync -av --exclude .venv --exclude 'frontend/node_modules' \
     --exclude 'frontend/dist' --exclude '__pycache__' \
     "./" user@YOUR_VM_IP:/opt/levelup/
   ```
   > `data/` holds `levelup.db` (~186 MB) — that's your whole state, keep it.
   > A *fresh* empty `data/` instead? Then after first start, seed the owner
   > row once (see README "Seed the single owner user").

2. **Point DNS at the VM** — an `A` record for `YOUR-DOMAIN.example.com` →
   the VM's public IP. Make sure ports **80 and 443** are open.

3. **Set your domain + login** in [Caddyfile](Caddyfile):
   - Replace `YOUR-DOMAIN.example.com` with your domain.
   - Generate a password hash and paste it into the `basic_auth` block:
     ```bash
     docker run --rm caddy caddy hash-password --plaintext 'STRONG-PASSWORD'
     ```
     Add one `username  hash` line per teammate.

4. **Start it** (from `/opt/levelup`):
   ```bash
   docker compose up -d --build
   ```
   First build takes a few minutes (it installs Chromium). It auto-runs DB
   migrations on start.

5. Open **https://YOUR-DOMAIN.example.com** and log in. Everyone shares the
   same data; changes are live for all.

## Nicer auth (optional, recommended): Cloudflare Access
Instead of a shared password, put **Cloudflare Tunnel + Access** in front for
real per-person SSO (email/Google login), revocable per teammate, with no
ports exposed on the VM. Point the tunnel at `app:8322` and drop the
`basic_auth` block from the Caddyfile. Worth it once you're past "just
testing."

## Operations
- **Logs:** `docker compose logs -f app`
- **Update after code changes:** redeploy with
  `docker compose up -d --build` (migrations run automatically).
- **Backups — do this:** the `data/` directory is the *entire* state. Snapshot
  it regularly. SQLite is safest to copy with the app stopped
  (`docker compose stop app`, copy `data/`, `docker compose start app`), or
  copy `data/levelup.db` plus its `-wal`/`-shm` files together.
- **Do not scale the app** to multiple workers/replicas — SQLite is
  single-writer and the enrichment auto-run is an in-process thread. One
  container is by design. A handful of concurrent editors is fine; if you
  outgrow that, switch `LEVELUP_DATABASE_URL` to Postgres.

## Notes specific to this app
- **Chromium is included** in the image, so JS-rendered / anti-bot school
  sites still enrich.
- **RSPO reachability:** the RSPO JSON API works from here; confirm it's
  reachable from your VM's region after first deploy (`docker compose exec app
  python -c "from levelup.services.enrichment.rspo_detail import fetch_rspo_detail as f; print(bool(f('12637')))"`).
- **No app-level accounts:** the login is the Caddy/Cloudflare gate; everyone
  who gets in is the single shared owner. That matches the "one team, one
  dataset" goal.
