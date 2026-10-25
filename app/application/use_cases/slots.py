from __future__ import annotations

from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo


def add_minutes_to_time(value: time, minutes: int) -> time:
    base_dt = datetime.combine(date.today(), value)
    shifted = base_dt + timedelta(minutes=minutes)
    return shifted.time().replace(microsecond=0)


def _build_candidate_slots(
    day_start: time,
    day_end: time,
    duration_min: int,
    buffer_min: int,
) -> list[tuple[time, time]]:
    candidates: list[tuple[time, time]] = []
    step = duration_min + buffer_min

    cursor = datetime.combine(date.today(), day_start)
    hard_end = datetime.combine(date.today(), day_end)
    duration = timedelta(minutes=duration_min)

    while cursor + duration <= hard_end:
        slot_start = cursor.time().replace(microsecond=0)
        slot_end = (cursor + duration).time().replace(microsecond=0)
        candidates.append((slot_start, slot_end))
        cursor += timedelta(minutes=step)

    return candidates


def _overlaps(slot_start: time, slot_end: time, busy_start: time, busy_end: time) -> bool:
    return slot_start < busy_end and busy_start < slot_end


def calculate_available_slots(
    target_date: date,
    day_start: time,
    day_end: time,
    duration_min: int,
    buffer_min: int,
    busy_slots: list[tuple[time, time]],
    timezone: str,
) -> list[tuple[time, time]]:
    tz = ZoneInfo(timezone)
    now = datetime.now(tz)

    available: list[tuple[time, time]] = []
    candidates = _build_candidate_slots(day_start, day_end, duration_min, buffer_min)

    for slot_start, slot_end in candidates:
        slot_dt = datetime.combine(target_date, slot_start).replace(tzinfo=tz)
        if slot_dt <= now:
            continue

        if any(_overlaps(slot_start, slot_end, busy_start, busy_end) for busy_start, busy_end in busy_slots):
            continue

        available.append((slot_start, slot_end))

    return available
