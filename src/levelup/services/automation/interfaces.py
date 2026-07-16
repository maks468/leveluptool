"""Contracts for outbound email, reminders, and event tracking. No
implementation exists yet -- see noop.py and registry.py. Pipeline code
calls these interfaces today (hitting the no-op); swapping in a real
implementation later means changing registry.py only.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol


@dataclass
class SendResult:
    status: str  # "sent" | "not_implemented"
    message_id: str | None = None


class EmailSender(Protocol):
    def send(self, *, to: str, subject: str, body: str, school_id: int, template: str | None = None) -> SendResult: ...


class ReminderScheduler(Protocol):
    def schedule(self, *, school_id: int, due_at: datetime, reason: str) -> str: ...
    def cancel(self, reminder_id: str) -> None: ...


class EventTracker(Protocol):
    def track_open(self, message_id: str) -> None: ...
