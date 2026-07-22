import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse

from levelup.api.v1.router import router as api_v1_router
from levelup.core.db import SessionLocal
from levelup.services.enrichment.auto_enrich import start_auto_enrich_thread, stop_auto_enrich_thread
from levelup.services.enrichment.jobs import reap_orphaned_jobs

# Built frontend (npm run build -> frontend/dist). When present, FastAPI
# serves it same-origin so the whole app is one process on one port -- no
# separate dev server, no CORS, no proxy -- which is exactly what a single
# always-on deployment wants. When absent (local dev), this is skipped and
# the Vite dev server on :5173 proxies /api here as before. Override the
# location with LEVELUP_FRONTEND_DIST (the Docker image sets it).
_DEFAULT_DIST = Path(__file__).resolve().parents[2] / "frontend" / "dist"
FRONTEND_DIST = Path(os.environ.get("LEVELUP_FRONTEND_DIST", _DEFAULT_DIST))


@asynccontextmanager
async def lifespan(app: FastAPI):
    session = SessionLocal()
    try:
        reap_orphaned_jobs(session)
    finally:
        session.close()
    start_auto_enrich_thread()
    yield
    stop_auto_enrich_thread()


app = FastAPI(title="LevelUp Schools CRM", lifespan=lifespan)

# Same-origin in production makes this irrelevant; kept (and made
# env-configurable) only for running the Vite dev server against a remote
# backend. Comma-separated origins.
_cors_origins = os.environ.get("LEVELUP_CORS_ORIGINS", "http://localhost:5173").split(",")
app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in _cors_origins if o.strip()],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(api_v1_router)


@app.get("/health")
def health():
    return {"status": "ok"}


if FRONTEND_DIST.is_dir():
    _dist_root = FRONTEND_DIST.resolve()
    _index = _dist_root / "index.html"

    @app.get("/{full_path:path}")
    def serve_spa(full_path: str):
        """Serve the built SPA: a real static asset if the path maps to one,
        otherwise index.html so client-side routes (/pipeline, /library, ...)
        resolve on a hard refresh or a shared deep link. API 404s stay JSON."""
        if full_path.startswith("api/"):
            raise HTTPException(status_code=404, detail="Not found")
        candidate = (_dist_root / full_path).resolve()
        if (
            full_path
            and candidate.is_file()
            and str(candidate).startswith(str(_dist_root))  # no path traversal out of dist
        ):
            return FileResponse(candidate)
        return FileResponse(_index)
