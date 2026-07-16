"""The single swap point for wiring in real automation later. Change the
factory bodies here -- nowhere else -- when a real EmailSender/
ReminderScheduler/EventTracker exists.
"""

from levelup.services.automation.interfaces import EmailSender, EventTracker, ReminderScheduler
from levelup.services.automation.noop import NoOpEmailSender, NoOpEventTracker, NoOpReminderScheduler


def get_email_sender() -> EmailSender:
    return NoOpEmailSender()


def get_reminder_scheduler() -> ReminderScheduler:
    return NoOpReminderScheduler()


def get_event_tracker() -> EventTracker:
    return NoOpEventTracker()
