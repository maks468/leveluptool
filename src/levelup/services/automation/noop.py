import logging
from datetime import datetime

from levelup.services.automation.interfaces import SendResult

logger = logging.getLogger("levelup.automation")


class NoOpEmailSender:
    def send(self, *, to: str, subject: str, body: str, school_id: int, template: str | None = None) -> SendResult:
        logger.info("NoOpEmailSender: would send %r to %s for school %s", subject, to, school_id)
        return SendResult(status="not_implemented")


class NoOpReminderScheduler:
    def schedule(self, *, school_id: int, due_at: datetime, reason: str) -> str:
        logger.info("NoOpReminderScheduler: would schedule %r for school %s at %s", reason, school_id, due_at)
        return "not_implemented"

    def cancel(self, reminder_id: str) -> None:
        logger.info("NoOpReminderScheduler: would cancel %s", reminder_id)


class NoOpEventTracker:
    def track_open(self, message_id: str) -> None:
        logger.info("NoOpEventTracker: would track open for %s", message_id)
