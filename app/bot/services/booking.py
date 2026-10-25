from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone
from typing import Optional, Sequence
from uuid import UUID
from zoneinfo import ZoneInfo

from sqlalchemy import and_, delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.use_cases.slots import add_minutes_to_time, calculate_available_slots
from app.bot.localization import normalize_locale
from app.infrastructure.config import Settings
from app.infrastructure.db.enums import (
    BookingStatus,
    NotificationStatus,
    NotificationType,
    UserRole,
)
from app.infrastructure.db.models import (
    Booking,
    Notification,
    Service,
    User,
    WaitlistEntry,
    WorkingHours,
)

REMINDER_NOTIFICATION_TYPES = (NotificationType.REMINDER_24H, NotificationType.REMINDER_2H)


async def list_active_services(session: AsyncSession) -> list[Service]:
    result = await session.execute(
        select(Service).where(Service.is_active.is_(True)).order_by(Service.name.asc())
    )
    return list(result.scalars().all())


async def get_service(session: AsyncSession, service_id: UUID) -> Optional[Service]:
    service = await session.get(Service, service_id)
    if service is None or not service.is_active:
        return None
    return service


async def get_working_weekdays(session: AsyncSession) -> set[int]:
    result = await session.execute(
        select(WorkingHours.weekday).where(WorkingHours.is_working_day.is_(True))
    )
    return {int(row.weekday) for row in result}


async def get_slots_for_service_date(
    session: AsyncSession,
    service: Service,
    target_date: date,
    settings: Settings,
) -> list[tuple[time, time]]:
    day_hours_result = await session.execute(
        select(WorkingHours).where(
            and_(
                WorkingHours.weekday == target_date.isoweekday(),
                WorkingHours.is_working_day.is_(True),
            )
        )
    )
    day_hours = day_hours_result.scalar_one_or_none()
    if day_hours is None:
        return []

    busy_result = await session.execute(
        select(Booking.start_time, Booking.end_time)
        .where(Booking.service_id == service.id)
        .where(Booking.date == target_date)
        .where(Booking.status != BookingStatus.CANCELLED)
    )
    busy_slots = [(row.start_time, row.end_time) for row in busy_result]

    return calculate_available_slots(
        target_date=target_date,
        day_start=day_hours.start_time,
        day_end=day_hours.end_time,
        duration_min=service.duration_min,
        buffer_min=settings.slot_buffer_min,
        busy_slots=busy_slots,
        timezone=settings.timezone,
    )


async def get_or_create_client(
    session: AsyncSession,
    telegram_id: int,
    full_name: str,
    phone: str,
    locale: str = "ru",
) -> User:
    normalized_locale = normalize_locale(locale)
    result = await session.execute(select(User).where(User.telegram_id == telegram_id))
    user = result.scalar_one_or_none()

    if user is None:
        user = User(
            telegram_id=telegram_id,
            full_name=full_name,
            phone=phone,
            locale=normalized_locale,
            role=UserRole.CLIENT,
        )
        session.add(user)
        await session.flush()
        return user

    user.full_name = full_name
    user.phone = phone
    user.locale = normalized_locale
    if user.role is None:
        user.role = UserRole.CLIENT
    await session.flush()
    return user


async def get_or_create_client_profile(
    session: AsyncSession,
    *,
    telegram_id: int,
    full_name: str,
    locale: str = "ru",
) -> User:
    normalized_locale = normalize_locale(locale)
    result = await session.execute(select(User).where(User.telegram_id == telegram_id))
    user = result.scalar_one_or_none()

    if user is None:
        user = User(
            telegram_id=telegram_id,
            full_name=full_name,
            phone=None,
            locale=normalized_locale,
            role=UserRole.CLIENT,
        )
        session.add(user)
        await session.flush()
        return user

    if not user.full_name and full_name:
        user.full_name = full_name
    user.locale = normalized_locale
    if user.role is None:
        user.role = UserRole.CLIENT
    await session.flush()
    return user


async def get_user_locale(session: AsyncSession, telegram_id: int) -> str | None:
    result = await session.execute(select(User.locale).where(User.telegram_id == telegram_id))
    return result.scalar_one_or_none()


def build_candidate_dates(working_weekdays: Sequence[int], horizon_days: int = 14) -> list[date]:
    weekdays = set(working_weekdays)
    if not weekdays:
        return []

    today = date.today()
    result: list[date] = []
    for offset in range(horizon_days):
        candidate = today + timedelta(days=offset)
        if candidate.isoweekday() in weekdays:
            result.append(candidate)
    return result


def parse_manager_chat_ids(raw: str) -> list[int]:
    ids: list[int] = []
    for part in raw.split(","):
        value = part.strip()
        if not value:
            continue
        try:
            ids.append(int(value))
        except ValueError:
            continue
    return ids


async def add_client_to_waitlist(
    session: AsyncSession,
    *,
    telegram_id: int,
    full_name: str,
    service_id: UUID,
    wait_date: date,
    comment: Optional[str] = None,
    locale: str = "ru",
) -> tuple[Optional[WaitlistEntry], bool, Optional[str]]:
    service = await get_service(session, service_id)
    if service is None:
        return None, False, "Услуга недоступна."

    client = await get_or_create_client_profile(
        session=session,
        telegram_id=telegram_id,
        full_name=full_name,
        locale=locale,
    )

    existing_result = await session.execute(
        select(WaitlistEntry).where(
            WaitlistEntry.client_id == client.id,
            WaitlistEntry.service_id == service.id,
            WaitlistEntry.date == wait_date,
        )
    )
    existing_entry = existing_result.scalar_one_or_none()
    if existing_entry is not None:
        return existing_entry, False, None

    entry = WaitlistEntry(
        client_id=client.id,
        service_id=service.id,
        date=wait_date,
        comment=comment,
        source="telegram",
    )
    session.add(entry)
    try:
        await session.commit()
    except IntegrityError:
        await session.rollback()
        duplicated_result = await session.execute(
            select(WaitlistEntry).where(
                WaitlistEntry.client_id == client.id,
                WaitlistEntry.service_id == service.id,
                WaitlistEntry.date == wait_date,
            )
        )
        duplicated = duplicated_result.scalar_one_or_none()
        if duplicated is not None:
            return duplicated, False, None
        return None, False, "Не удалось добавить в лист ожидания."

    await session.refresh(entry)
    return entry, True, None


async def create_booking_for_client(
    session: AsyncSession,
    settings: Settings,
    telegram_id: int,
    full_name: str,
    phone: str,
    service: Service,
    booking_date: date,
    start_time: time,
    source: str = "telegram",
    locale: str = "ru",
) -> Booking:
    tz = ZoneInfo(settings.timezone)
    starts_at = datetime.combine(booking_date, start_time).replace(tzinfo=tz)
    now = datetime.now(tz)
    if starts_at <= now:
        raise ValueError("Нельзя записаться на прошедшее время.")

    client = await get_or_create_client(
        session=session,
        telegram_id=telegram_id,
        full_name=full_name,
        phone=phone,
        locale=locale,
    )
    end_time = add_minutes_to_time(start_time, service.duration_min)

    booking = Booking(
        client_id=client.id,
        service_id=service.id,
        date=booking_date,
        start_time=start_time,
        end_time=end_time,
        status=BookingStatus.NEW,
        source=source,
    )
    session.add(booking)
    await session.flush()

    starts_at_utc = starts_at.astimezone(timezone.utc)
    now_utc = datetime.now(timezone.utc)
    schedules = [
        (NotificationType.REMINDER_24H, starts_at_utc - timedelta(hours=24)),
        (NotificationType.REMINDER_2H, starts_at_utc - timedelta(hours=2)),
    ]
    for notification_type, scheduled_at in schedules:
        if scheduled_at > now_utc:
            session.add(
                Notification(
                    booking_id=booking.id,
                    type=notification_type,
                    scheduled_at=scheduled_at,
                )
            )

    await session.commit()
    await session.refresh(booking)
    return booking


async def _replace_pending_reminders_for_booking(
    *,
    session: AsyncSession,
    booking: Booking,
    timezone_name: str,
) -> None:
    await session.execute(
        delete(Notification)
        .where(Notification.booking_id == booking.id)
        .where(Notification.status == NotificationStatus.PENDING)
        .where(Notification.type.in_(REMINDER_NOTIFICATION_TYPES))
    )

    starts_at_local = datetime.combine(booking.date, booking.start_time).replace(
        tzinfo=ZoneInfo(timezone_name)
    )
    starts_at_utc = starts_at_local.astimezone(timezone.utc)
    now_utc = datetime.now(timezone.utc)
    schedules = [
        (NotificationType.REMINDER_24H, starts_at_utc - timedelta(hours=24)),
        (NotificationType.REMINDER_2H, starts_at_utc - timedelta(hours=2)),
    ]

    for notification_type, scheduled_at in schedules:
        if scheduled_at > now_utc:
            session.add(
                Notification(
                    booking_id=booking.id,
                    type=notification_type,
                    scheduled_at=scheduled_at,
                )
            )


async def list_client_bookings(
    session: AsyncSession,
    telegram_id: int,
    limit: int = 10,
) -> list[tuple[Booking, Service]]:
    user_result = await session.execute(select(User).where(User.telegram_id == telegram_id))
    user = user_result.scalar_one_or_none()
    if user is None:
        return []

    result = await session.execute(
        select(Booking, Service)
        .join(Service, Booking.service_id == Service.id)
        .where(Booking.client_id == user.id)
        .order_by(Booking.date.desc(), Booking.start_time.desc())
        .limit(limit)
    )
    return [(row.Booking, row.Service) for row in result]


async def get_latest_client_booking_with_service(
    session: AsyncSession,
    *,
    telegram_id: int,
) -> tuple[Optional[User], Optional[Booking], Optional[Service]]:
    user_result = await session.execute(select(User).where(User.telegram_id == telegram_id))
    user = user_result.scalar_one_or_none()
    if user is None:
        return None, None, None

    result = await session.execute(
        select(Booking, Service)
        .join(Service, Booking.service_id == Service.id)
        .where(Booking.client_id == user.id)
        .order_by(Booking.created_at.desc(), Booking.date.desc(), Booking.start_time.desc())
        .limit(1)
    )
    row = result.first()
    if row is None:
        return user, None, None
    return user, row.Booking, row.Service


async def cancel_booking_for_client(
    session: AsyncSession,
    booking_id: UUID,
    telegram_id: int,
) -> tuple[Optional[Booking], bool]:
    user_result = await session.execute(select(User).where(User.telegram_id == telegram_id))
    user = user_result.scalar_one_or_none()
    if user is None:
        return None, False

    booking_result = await session.execute(
        select(Booking).where(Booking.id == booking_id, Booking.client_id == user.id)
    )
    booking = booking_result.scalar_one_or_none()
    if booking is None:
        return None, False

    if booking.status in {BookingStatus.DONE, BookingStatus.CANCELLED, BookingStatus.NO_SHOW}:
        return booking, False

    booking.status = BookingStatus.CANCELLED
    await session.execute(
        delete(Notification)
        .where(Notification.booking_id == booking.id)
        .where(Notification.status == NotificationStatus.PENDING)
        .where(Notification.type.in_(REMINDER_NOTIFICATION_TYPES))
    )
    await session.commit()
    await session.refresh(booking)
    return booking, True


async def get_client_booking_with_service(
    session: AsyncSession,
    *,
    booking_id: UUID,
    telegram_id: int,
) -> tuple[Optional[Booking], Optional[Service]]:
    user_result = await session.execute(select(User).where(User.telegram_id == telegram_id))
    user = user_result.scalar_one_or_none()
    if user is None:
        return None, None

    booking_result = await session.execute(
        select(Booking).where(Booking.id == booking_id, Booking.client_id == user.id)
    )
    booking = booking_result.scalar_one_or_none()
    if booking is None:
        return None, None

    service = await session.get(Service, booking.service_id)
    return booking, service


async def reschedule_booking_for_client(
    session: AsyncSession,
    *,
    settings: Settings,
    booking_id: UUID,
    telegram_id: int,
    new_date: date,
    new_start_time: time,
) -> tuple[Optional[Booking], Optional[Service], Optional[str]]:
    booking, service = await get_client_booking_with_service(
        session,
        booking_id=booking_id,
        telegram_id=telegram_id,
    )
    if booking is None:
        return None, None, "Запись не найдена."
    if service is None or not service.is_active:
        return None, None, "Услуга недоступна для переноса."

    if booking.status in {BookingStatus.DONE, BookingStatus.CANCELLED, BookingStatus.NO_SHOW}:
        return booking, service, "Эту запись уже нельзя перенести."

    if booking.date == new_date and booking.start_time == new_start_time:
        return booking, service, "Вы выбрали текущие дату и время."

    available_slots = await get_slots_for_service_date(
        session=session,
        service=service,
        target_date=new_date,
        settings=settings,
    )
    allowed_starts = {slot_start for slot_start, _slot_end in available_slots}
    if new_start_time not in allowed_starts:
        return booking, service, "Этот слот уже недоступен. Выберите другой."

    booking.date = new_date
    booking.start_time = new_start_time
    booking.end_time = add_minutes_to_time(new_start_time, service.duration_min)
    booking.status = BookingStatus.NEW

    try:
        await _replace_pending_reminders_for_booking(
            session=session,
            booking=booking,
            timezone_name=settings.timezone,
        )
        await session.commit()
    except IntegrityError:
        await session.rollback()
        return booking, service, "Этот слот только что заняли. Выберите другой."

    await session.refresh(booking)
    return booking, service, None


async def confirm_booking_by_reminder(
    session: AsyncSession,
    *,
    booking_id: UUID,
    telegram_id: int,
) -> tuple[Optional[Booking], bool, str]:
    booking, _service = await get_client_booking_with_service(
        session,
        booking_id=booking_id,
        telegram_id=telegram_id,
    )
    if booking is None:
        return None, False, "Запись не найдена."

    if booking.status == BookingStatus.CONFIRMED:
        return booking, False, "Запись уже подтверждена."
    if booking.status in {BookingStatus.DONE, BookingStatus.CANCELLED, BookingStatus.NO_SHOW}:
        return booking, False, "Эту запись уже нельзя подтвердить."

    booking.status = BookingStatus.CONFIRMED
    await session.commit()
    await session.refresh(booking)
    return booking, True, "Отлично, визит подтверждён."


async def decline_booking_by_reminder(
    session: AsyncSession,
    *,
    booking_id: UUID,
    telegram_id: int,
) -> tuple[Optional[Booking], bool, str]:
    booking, _service = await get_client_booking_with_service(
        session,
        booking_id=booking_id,
        telegram_id=telegram_id,
    )
    if booking is None:
        return None, False, "Запись не найдена."
    if booking.status == BookingStatus.CANCELLED:
        return booking, False, "Запись уже отменена."
    if booking.status in {BookingStatus.DONE, BookingStatus.NO_SHOW}:
        return booking, False, "Эту запись уже нельзя отменить."

    note = "[CLIENT_DECLINED_REMINDER] Клиент нажал «Не приду» в напоминании"
    old_comment = (booking.comment or "").strip()
    booking.comment = note if not old_comment else f"{old_comment}\n\n{note}"
    booking.status = BookingStatus.CANCELLED
    await session.execute(
        delete(Notification)
        .where(Notification.booking_id == booking.id)
        .where(Notification.status == NotificationStatus.PENDING)
        .where(Notification.type.in_(REMINDER_NOTIFICATION_TYPES))
    )
    await session.commit()
    await session.refresh(booking)
    return booking, True, "Поняли, запись отменена."


async def update_booking_status_by_admin(
    session: AsyncSession,
    *,
    booking_id: UUID,
    target_status: BookingStatus,
    timezone_name: Optional[str] = None,
) -> tuple[Optional[Booking], Optional[Service], Optional[User], Optional[str]]:
    booking = await session.get(Booking, booking_id)
    if booking is None:
        return None, None, None, "Запись не найдена."

    current = booking.status
    if current == target_status:
        return booking, None, None, "Статус уже установлен."

    if target_status == BookingStatus.CONFIRMED:
        if current != BookingStatus.NEW:
            return booking, None, None, "Подтвердить можно только запись в статусе «Новая»."
    elif target_status in {BookingStatus.DONE, BookingStatus.NO_SHOW}:
        if current != BookingStatus.CONFIRMED:
            return booking, None, None, "Этот статус можно поставить только из «Подтверждена»."
        if target_status == BookingStatus.NO_SHOW and timezone_name:
            tz = ZoneInfo(timezone_name)
            visit_dt = datetime.combine(booking.date, booking.start_time).replace(tzinfo=tz)
            if visit_dt > datetime.now(tz):
                return booking, None, None, "No-show можно поставить только после времени визита."
    else:
        return booking, None, None, "Недопустимый целевой статус."

    booking.status = target_status
    await session.commit()
    await session.refresh(booking)

    service = await session.get(Service, booking.service_id)
    client = await session.get(User, booking.client_id)
    return booking, service, client, None
