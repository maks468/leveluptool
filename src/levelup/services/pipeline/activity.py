"""Append-only writer for activity_log. No update/delete is exposed here
or anywhere else -- that's what makes it append-only in practice, not
just by convention.
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from levelup.models.pipeline import ActivityLog


def log_activity(
    session: Session,
    *,
    school_id: int,
    activity_type: str,
    actor_id: int | None = None,
    from_stage: str | None = None,
    to_stage: str | None = None,
    note: str | None = None,
    metadata: dict | None = None,
) -> ActivityLog:
    entry = ActivityLog(
        school_id=school_id,
        actor_id=actor_id,
        activity_type=activity_type,
        from_stage=from_stage,
        to_stage=to_stage,
        note=note,
        metadata_json=metadata or {},
    )
    session.add(entry)
    session.flush()
    return entry
