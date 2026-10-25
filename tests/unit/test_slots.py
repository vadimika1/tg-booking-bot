from __future__ import annotations

from datetime import date, time, timedelta

from app.application.use_cases.slots import calculate_available_slots


def test_calculate_available_slots_excludes_busy_ranges() -> None:
    target_date = date.today() + timedelta(days=1)
    slots = calculate_available_slots(
        target_date=target_date,
        day_start=time(10, 0),
        day_end=time(12, 0),
        duration_min=30,
        buffer_min=0,
        busy_slots=[(time(10, 30), time(11, 0))],
        timezone="Europe/Moscow",
    )

    assert (time(10, 30), time(11, 0)) not in slots
    assert (time(10, 0), time(10, 30)) in slots
    assert (time(11, 0), time(11, 30)) in slots


def test_calculate_available_slots_hides_past_time_for_today() -> None:
    target_date = date.today() - timedelta(days=1)
    slots = calculate_available_slots(
        target_date=target_date,
        day_start=time(0, 0),
        day_end=time(12, 0),
        duration_min=10,
        buffer_min=0,
        busy_slots=[],
        timezone="Europe/Moscow",
    )

    assert slots == []
