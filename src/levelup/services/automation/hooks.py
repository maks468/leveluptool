"""Call points the pipeline service already exercises today, hitting the
no-op registry. Wiring in real automation later touches registry.py only
-- this file's call sites don't need to change.
"""

from datetime import datetime

from levelup.services.automation import registry


def on_stage_changed(*, school_id: int, from_stage: str, to_stage: str) -> None:
    registry.get_reminder_scheduler()  # real implementations will decide whether to (re)schedule here


def on_next_action_set(*, school_id: int, due_at: datetime, reason: str) -> None:
    registry.get_reminder_scheduler().schedule(school_id=school_id, due_at=due_at, reason=reason)
