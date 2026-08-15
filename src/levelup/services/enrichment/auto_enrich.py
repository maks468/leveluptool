"""Background auto-enrich cycle -- gets the whole school library enriched
over time ("N schools per interval") without manually selecting batches
every time. Runs on a daemon thread started at app startup; a single
AutoEnrichSettings row (singleton, id=1) controls whether it's on and how
fast it runs, so the frontend can toggle it via a plain settings PATCH.
"""

from __future__ import annotations

import logging
import threading
from datetime import datetime, timezone

from levelup.core.config import settings as app_settings
from levelup.core.db import SessionLocal
from levelup.models.admin import AutoEnrichSettings
from levelup.models.enrichment import EnrichmentJobItem
from levelup.models.score import CurrentScore, SchoolScore
from levelup.models.school import TARGET_SCHOOL_CONDITIONS, School
from levelup.services.enrichment.jobs import create_job, run_job

logger = logging.getLogger(__name__)

POLL_SECONDS = 60


def _get_or_create_settings(session) -> AutoEnrichSettings:
    settings = session.query(AutoEnrichSettings).filter_by(id=1).one_or_none()
    if settings is None:
        settings = AutoEnrichSettings(id=1)
        session.add(settings)
        session.commit()
    return settings


def _select_candidate_school_ids(session, limit: int) -> list[int]:
    """Never re-picks a school that already went through an enrichment
    attempt (success or failed) -- otherwise a handful of dead-end schools
    (no website, unreachable) would get retried forever every cycle instead
    of making room for schools never yet touched. Highest score first, so
    the most promising schools reach full coverage soonest.

    "pending"/"running" items exclude a school too: a manual batch and this
    auto cycle run on separate threads, and picking a school the manual
    batch is CURRENTLY mid-way through had both threads writing the same
    school's contacts at once (two sessions, each blind to the other's
    uncommitted rows -- duplicate contacts, interleaved last-writer-wins
    on the School fields). A school legitimately awaiting its turn simply
    isn't a candidate for a second, simultaneous turn."""
    attempted = (
        session.query(EnrichmentJobItem.school_id)
        .filter(EnrichmentJobItem.status.in_(["success", "failed", "pending", "running"]))
        .distinct()
    )
    rows = (
        session.query(School.id)
        .outerjoin(CurrentScore, CurrentScore.school_id == School.id)
        .outerjoin(SchoolScore, SchoolScore.id == CurrentScore.score_id)
        # Same "target school" definition the whole API uses (see
        # models/school.py) -- never spend a crawl on an adult-education or
        # special-needs school.
        .filter(*TARGET_SCHOOL_CONDITIONS)
        .filter(~School.id.in_(attempted))
        .order_by(SchoolScore.total_score.desc().nulls_last())
        .limit(limit)
        .all()
    )
    return [row[0] for row in rows]


def run_auto_enrich_cycle() -> int | None:
    """Runs one check-and-maybe-enrich cycle against its own DB session.
    Returns the number of schools enqueued, or None if the cycle didn't run
    (disabled, or not due yet given interval_minutes)."""
    session = SessionLocal()
    try:
        settings = _get_or_create_settings(session)
        if not settings.enabled:
            return None

        now = datetime.now(timezone.utc)
        if settings.last_run_at is not None:
            last_run = settings.last_run_at.replace(tzinfo=timezone.utc)
            if (now - last_run).total_seconds() < settings.interval_minutes * 60:
                return None

        school_ids = _select_candidate_school_ids(session, settings.schools_per_run)
        settings.last_run_at = now
        settings.last_run_found_count = len(school_ids)
        session.commit()

        if not school_ids:
            return 0

        job = create_job(session, school_ids, requested_by=app_settings.default_owner_id, is_automatic=True)
        job_id = job.id
    finally:
        session.close()

    run_job(job_id)
    return len(school_ids)


_stop_event: threading.Event | None = None
_thread: threading.Thread | None = None


def _loop(stop_event: threading.Event) -> None:
    while not stop_event.is_set():
        try:
            run_auto_enrich_cycle()
        except Exception:  # noqa: BLE001 -- a bad cycle must never kill the thread
            logger.exception("Auto-enrich cycle failed")
        stop_event.wait(POLL_SECONDS)


def start_auto_enrich_thread() -> None:
    global _stop_event, _thread
    if _thread is not None:
        return
    _stop_event = threading.Event()
    _thread = threading.Thread(target=_loop, args=(_stop_event,), daemon=True, name="auto-enrich")
    _thread.start()


def stop_auto_enrich_thread() -> None:
    global _stop_event, _thread
    if _stop_event is not None:
        _stop_event.set()
    _thread = None
    _stop_event = None
