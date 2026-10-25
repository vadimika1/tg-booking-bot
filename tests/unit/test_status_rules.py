from __future__ import annotations

from app.infrastructure.db.enums import BookingStatus
from app.worker.main import _is_terminal_booking_status


def test_terminal_statuses_are_blocked_for_notifications() -> None:
    assert _is_terminal_booking_status(BookingStatus.CANCELLED) is True
    assert _is_terminal_booking_status(BookingStatus.DONE) is True
    assert _is_terminal_booking_status(BookingStatus.NO_SHOW) is True


def test_active_statuses_are_allowed_for_notifications() -> None:
    assert _is_terminal_booking_status(BookingStatus.NEW) is False
    assert _is_terminal_booking_status(BookingStatus.CONFIRMED) is False
