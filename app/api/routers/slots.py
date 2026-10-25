from __future__ import annotations

from datetime import date
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.schemas import SlotOut
from app.application.use_cases.slots import calculate_available_slots
from app.infrastructure.config import get_settings
from app.infrastructure.db.enums import BookingStatus
from app.infrastructure.db.models import Booking, Service, WorkingHours
from app.infrastructure.db.session import get_db_session

router = APIRouter(prefix="/api/slots", tags=["slots"])


@router.get("", response_model=list[SlotOut])
async def get_available_slots(
    service_id: UUID = Query(...),
    target_date: date = Query(..., alias="date"),
    session: AsyncSession = Depends(get_db_session),
) -> list[SlotOut]:
    settings = get_settings()

    service = await session.get(Service, service_id)
    if service is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Service not found")
    if not service.is_active:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Service is inactive")

    weekday = target_date.isoweekday()
    day_hours_result = await session.execute(
        select(WorkingHours).where(WorkingHours.weekday == weekday)
    )
    day_hours = day_hours_result.scalar_one_or_none()
    if day_hours is None or not day_hours.is_working_day:
        return []

    busy_result = await session.execute(
        select(Booking.start_time, Booking.end_time)
        .where(Booking.service_id == service_id)
        .where(Booking.date == target_date)
        .where(Booking.status != BookingStatus.CANCELLED)
    )

    busy_slots = [(row.start_time, row.end_time) for row in busy_result]

    slots = calculate_available_slots(
        target_date=target_date,
        day_start=day_hours.start_time,
        day_end=day_hours.end_time,
        duration_min=service.duration_min,
        buffer_min=settings.slot_buffer_min,
        busy_slots=busy_slots,
        timezone=settings.timezone,
    )

    return [SlotOut(start_time=start, end_time=end) for start, end in slots]
