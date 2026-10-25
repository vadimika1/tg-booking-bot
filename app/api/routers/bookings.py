from __future__ import annotations

import logging
from datetime import date, datetime
from typing import Optional
from uuid import UUID
from zoneinfo import ZoneInfo

from aiogram import Bot
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.schemas import BookingAdminCancel, BookingCreate, BookingOut, BookingStatusUpdate
from app.application.use_cases.slots import add_minutes_to_time
from app.infrastructure.config import get_settings
from app.infrastructure.db.enums import BookingStatus
from app.infrastructure.db.models import Booking, Service, User
from app.infrastructure.db.session import get_db_session

router = APIRouter(prefix="/api/bookings", tags=["bookings"])
logger = logging.getLogger(__name__)


def _build_admin_cancel_message(
    *,
    service_name: str,
    booking_date: date,
    start_time: str,
    reason: str,
) -> str:
    return (
        "❌ Ваша запись отменена администратором.\n\n"
        f"🧾 Услуга: <b>{service_name}</b>\n\n"
        f"📅 Дата: <b>{booking_date.strftime('%d.%m.%Y')}</b>\n\n"
        f"🕒 Время: <b>{start_time}</b>\n\n"
        f"📝 Причина: <b>{reason}</b>\n\n"
        "Если хотите, выберите новую дату в боте."
    )


async def _notify_client_admin_cancel(
    *,
    client_telegram_id: int,
    service_name: str,
    booking_date: date,
    start_time: str,
    reason: str,
) -> None:
    settings = get_settings()
    if not settings.telegram_bot_token or settings.telegram_bot_token == "replace_me":
        return

    text = _build_admin_cancel_message(
        service_name=service_name,
        booking_date=booking_date,
        start_time=start_time,
        reason=reason,
    )
    bot = Bot(
        token=settings.telegram_bot_token,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    try:
        await bot.send_message(chat_id=client_telegram_id, text=text)
    finally:
        await bot.session.close()


@router.get("", response_model=list[BookingOut])
async def list_bookings(
    booking_date: Optional[date] = Query(default=None, alias="date"),
    status_filter: Optional[BookingStatus] = Query(default=None, alias="status"),
    session: AsyncSession = Depends(get_db_session),
) -> list[Booking]:
    query = select(Booking)
    if booking_date is not None:
        query = query.where(Booking.date == booking_date)
    if status_filter is not None:
        query = query.where(Booking.status == status_filter)

    query = query.order_by(Booking.date.desc(), Booking.start_time.desc())
    result = await session.execute(query.limit(200))
    return list(result.scalars().all())


@router.post("", response_model=BookingOut, status_code=status.HTTP_201_CREATED)
async def create_booking(
    payload: BookingCreate,
    session: AsyncSession = Depends(get_db_session),
) -> Booking:
    settings = get_settings()
    tz = ZoneInfo(settings.timezone)

    starts_at = datetime.combine(payload.date, payload.start_time).replace(tzinfo=tz)
    if starts_at <= datetime.now(tz):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Cannot book past time")

    service = await session.get(Service, payload.service_id)
    if service is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Service not found")
    if not service.is_active:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Service is inactive")

    client = await session.get(User, payload.client_id)
    if client is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Client not found")

    end_time = payload.end_time or add_minutes_to_time(payload.start_time, service.duration_min)
    if payload.start_time >= end_time:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid booking time range")

    booking = Booking(
        client_id=payload.client_id,
        service_id=payload.service_id,
        date=payload.date,
        start_time=payload.start_time,
        end_time=end_time,
        status=BookingStatus.NEW,
        comment=payload.comment,
        source=payload.source,
    )

    session.add(booking)

    try:
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Time slot is already booked",
        ) from exc

    await session.refresh(booking)
    return booking


@router.patch("/{booking_id}/status", response_model=BookingOut)
async def update_booking_status(
    booking_id: UUID,
    payload: BookingStatusUpdate,
    session: AsyncSession = Depends(get_db_session),
) -> Booking:
    booking = await session.get(Booking, booking_id)
    if booking is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Booking not found")

    if payload.status == BookingStatus.CANCELLED:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Use /api/bookings/{id}/admin-cancel with reason for cancellation",
        )

    booking.status = payload.status
    await session.commit()
    await session.refresh(booking)
    return booking


@router.post("/{booking_id}/admin-cancel", response_model=BookingOut)
async def admin_cancel_booking(
    booking_id: UUID,
    payload: BookingAdminCancel,
    session: AsyncSession = Depends(get_db_session),
) -> Booking:
    booking = await session.get(Booking, booking_id)
    if booking is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Booking not found")

    if booking.status in {BookingStatus.DONE, BookingStatus.NO_SHOW}:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot cancel booking in terminal status",
        )
    if booking.status == BookingStatus.CANCELLED:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Booking is already cancelled",
        )

    reason = payload.reason.strip()
    if not reason:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Cancellation reason is required",
        )

    old_comment = (booking.comment or "").strip()
    reason_comment = f"[ADMIN_CANCEL_REASON] {reason}"
    booking.comment = reason_comment if not old_comment else f"{old_comment}\n\n{reason_comment}"
    booking.status = BookingStatus.CANCELLED

    await session.commit()
    await session.refresh(booking)

    if payload.notify_client:
        client = await session.get(User, booking.client_id)
        service = await session.get(Service, booking.service_id)
        if client is not None and service is not None:
            try:
                await _notify_client_admin_cancel(
                    client_telegram_id=client.telegram_id,
                    service_name=service.name,
                    booking_date=booking.date,
                    start_time=booking.start_time.strftime("%H:%M"),
                    reason=reason,
                )
            except Exception:
                logger.exception(
                    "Failed to notify client about admin cancellation",
                    extra={"booking_id": str(booking.id), "client_id": str(client.id)},
                )

    return booking
