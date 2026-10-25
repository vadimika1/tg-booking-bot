from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from typing import Optional
from zoneinfo import ZoneInfo

from sqlalchemy import func, select

from app.application.use_cases.slots import add_minutes_to_time
from app.infrastructure.config import get_settings
from app.infrastructure.db.enums import BookingStatus, NotificationStatus, NotificationType, UserRole
from app.infrastructure.db.models import (
    AuditLog,
    Booking,
    Notification,
    Service,
    User,
    WaitlistEntry,
    WorkingHours,
)
from app.infrastructure.db.session import get_session_factory
from scripts.seed_demo_data import upsert_services, upsert_working_hours


@dataclass(frozen=True)
class DemoClient:
    telegram_id: int
    full_name: str
    phone: str


@dataclass(frozen=True)
class DemoBooking:
    service_name: str
    telegram_id: int
    days_offset: int
    start_time: time
    status: BookingStatus
    comment: Optional[str] = None


@dataclass(frozen=True)
class DemoWaitlist:
    service_name: str
    telegram_id: int
    days_offset: int
    comment: Optional[str] = None


DEMO_CLIENTS: tuple[DemoClient, ...] = (
    DemoClient(telegram_id=7900000001, full_name="Анна Иванова", phone="+375291111111"),
    DemoClient(telegram_id=7900000002, full_name="Мария Петрова", phone="+375292222222"),
    DemoClient(telegram_id=7900000003, full_name="Екатерина Соколова", phone="+375293333333"),
    DemoClient(telegram_id=7900000004, full_name="Ольга Кузнецова", phone="+375294444444"),
    DemoClient(telegram_id=7900000005, full_name="Светлана Орлова", phone="+375295555555"),
    DemoClient(telegram_id=7900000006, full_name="Ирина Волкова", phone="+375296666666"),
    DemoClient(telegram_id=7900000007, full_name="Дарья Лебедева", phone="+375297777777"),
)

DEMO_BOOKINGS: tuple[DemoBooking, ...] = (
    DemoBooking(
        service_name="Женская стрижка",
        telegram_id=7900000001,
        days_offset=1,
        start_time=time(10, 0),
        status=BookingStatus.NEW,
    ),
    DemoBooking(
        service_name="Мужская стрижка",
        telegram_id=7900000002,
        days_offset=1,
        start_time=time(12, 0),
        status=BookingStatus.CONFIRMED,
    ),
    DemoBooking(
        service_name="Маникюр классический",
        telegram_id=7900000003,
        days_offset=2,
        start_time=time(11, 0),
        status=BookingStatus.NEW,
    ),
    DemoBooking(
        service_name="Дневной макияж",
        telegram_id=7900000004,
        days_offset=2,
        start_time=time(15, 0),
        status=BookingStatus.CONFIRMED,
    ),
    DemoBooking(
        service_name="Коррекция бровей",
        telegram_id=7900000005,
        days_offset=-1,
        start_time=time(10, 0),
        status=BookingStatus.DONE,
        comment="Визит завершён",
    ),
    DemoBooking(
        service_name="Окрашивание корней",
        telegram_id=7900000006,
        days_offset=-1,
        start_time=time(13, 0),
        status=BookingStatus.CANCELLED,
        comment="Клиент отменил запись",
    ),
    DemoBooking(
        service_name="Женская стрижка",
        telegram_id=7900000007,
        days_offset=-2,
        start_time=time(16, 0),
        status=BookingStatus.NO_SHOW,
        comment="Клиент не пришёл",
    ),
)

DEMO_WAITLIST: tuple[DemoWaitlist, ...] = (
    DemoWaitlist("Женская стрижка", 7900000001, 1, "Нужно после 18:00"),
    DemoWaitlist("Маникюр классический", 7900000002, 2, "Только утром"),
    DemoWaitlist("Окрашивание корней", 7900000003, 3, "Любой свободный слот"),
)


async def _ensure_users() -> tuple[dict[int, User], int, int]:
    created = 0
    updated = 0
    users_by_telegram: dict[int, User] = {}

    session_factory = get_session_factory()
    async with session_factory() as session:
        for item in DEMO_CLIENTS:
            result = await session.execute(select(User).where(User.telegram_id == item.telegram_id))
            user = result.scalar_one_or_none()
            if user is None:
                user = User(
                    telegram_id=item.telegram_id,
                    full_name=item.full_name,
                    phone=item.phone,
                    role=UserRole.CLIENT,
                )
                session.add(user)
                await session.flush()
                created += 1
            else:
                user.full_name = item.full_name
                user.phone = item.phone
                if user.role != UserRole.CLIENT:
                    user.role = UserRole.CLIENT
                updated += 1
            users_by_telegram[item.telegram_id] = user

        await session.commit()

    return users_by_telegram, created, updated


async def _load_services() -> dict[str, Service]:
    session_factory = get_session_factory()
    async with session_factory() as session:
        result = await session.execute(select(Service).where(Service.is_active.is_(True)))
        rows = result.scalars().all()
        return {item.name: item for item in rows}


async def _ensure_bookings(
    *,
    users_by_telegram: dict[int, User],
    services_by_name: dict[str, Service],
) -> tuple[list[Booking], int, int]:
    created = 0
    updated = 0
    seeded: list[Booking] = []

    session_factory = get_session_factory()
    async with session_factory() as session:
        for item in DEMO_BOOKINGS:
            user = users_by_telegram.get(item.telegram_id)
            service = services_by_name.get(item.service_name)
            if user is None or service is None:
                continue

            booking_date = date.today() + timedelta(days=item.days_offset)
            end_time = add_minutes_to_time(item.start_time, service.duration_min)

            existing_result = await session.execute(
                select(Booking).where(
                    Booking.service_id == service.id,
                    Booking.date == booking_date,
                    Booking.start_time == item.start_time,
                )
            )
            booking = existing_result.scalar_one_or_none()

            if booking is None:
                booking = Booking(
                    client_id=user.id,
                    service_id=service.id,
                    date=booking_date,
                    start_time=item.start_time,
                    end_time=end_time,
                    status=item.status,
                    comment=item.comment,
                    source="seed_full_demo",
                )
                session.add(booking)
                await session.flush()
                created += 1
            else:
                booking.client_id = user.id
                booking.end_time = end_time
                booking.status = item.status
                booking.comment = item.comment
                booking.source = "seed_full_demo"
                updated += 1

            seeded.append(booking)

        await session.commit()

    return seeded, created, updated


async def _ensure_waitlist(
    *,
    users_by_telegram: dict[int, User],
    services_by_name: dict[str, Service],
) -> tuple[int, int]:
    created = 0
    updated = 0

    session_factory = get_session_factory()
    async with session_factory() as session:
        for item in DEMO_WAITLIST:
            user = users_by_telegram.get(item.telegram_id)
            service = services_by_name.get(item.service_name)
            if user is None or service is None:
                continue

            wait_date = date.today() + timedelta(days=item.days_offset)
            existing_result = await session.execute(
                select(WaitlistEntry).where(
                    WaitlistEntry.client_id == user.id,
                    WaitlistEntry.service_id == service.id,
                    WaitlistEntry.date == wait_date,
                )
            )
            entry = existing_result.scalar_one_or_none()
            if entry is None:
                entry = WaitlistEntry(
                    client_id=user.id,
                    service_id=service.id,
                    date=wait_date,
                    comment=item.comment,
                    source="seed_full_demo",
                )
                session.add(entry)
                created += 1
            else:
                entry.comment = item.comment
                entry.source = "seed_full_demo"
                updated += 1

        await session.commit()

    return created, updated


async def _ensure_notifications(bookings: list[Booking]) -> tuple[int, int]:
    created = 0
    updated = 0
    settings = get_settings()
    now_utc = datetime.now(timezone.utc)
    local_tz = ZoneInfo(settings.timezone)

    session_factory = get_session_factory()
    async with session_factory() as session:
        refreshed: list[Booking] = []
        for booking in bookings:
            db_booking = await session.get(Booking, booking.id)
            if db_booking is not None:
                refreshed.append(db_booking)

        for booking in refreshed:
            if booking.status not in {BookingStatus.NEW, BookingStatus.CONFIRMED}:
                continue

            starts_at_local = datetime.combine(booking.date, booking.start_time).replace(tzinfo=local_tz)
            starts_at_utc = starts_at_local.astimezone(timezone.utc)
            for notification_type, delta in (
                (NotificationType.REMINDER_24H, timedelta(hours=24)),
                (NotificationType.REMINDER_2H, timedelta(hours=2)),
            ):
                scheduled_at = starts_at_utc - delta
                if scheduled_at <= now_utc:
                    continue
                existing_result = await session.execute(
                    select(Notification).where(
                        Notification.booking_id == booking.id,
                        Notification.type == notification_type,
                        Notification.status == NotificationStatus.PENDING,
                    )
                )
                existing = existing_result.scalar_one_or_none()
                if existing is None:
                    session.add(
                        Notification(
                            booking_id=booking.id,
                            type=notification_type,
                            scheduled_at=scheduled_at,
                            status=NotificationStatus.PENDING,
                            attempts=0,
                        )
                    )
                    created += 1
                else:
                    existing.scheduled_at = scheduled_at
                    updated += 1

        if refreshed:
            done_booking = next((item for item in refreshed if item.status == BookingStatus.DONE), None)
            if done_booking is not None:
                sent_result = await session.execute(
                    select(Notification).where(
                        Notification.booking_id == done_booking.id,
                        Notification.type == NotificationType.REMINDER_24H,
                        Notification.status == NotificationStatus.SENT,
                    )
                )
                sent_item = sent_result.scalar_one_or_none()
                if sent_item is None:
                    session.add(
                        Notification(
                            booking_id=done_booking.id,
                            type=NotificationType.REMINDER_24H,
                            scheduled_at=now_utc - timedelta(days=2),
                            sent_at=now_utc - timedelta(days=2),
                            status=NotificationStatus.SENT,
                            attempts=1,
                        )
                    )
                    created += 1

            cancelled_booking = next(
                (item for item in refreshed if item.status == BookingStatus.CANCELLED),
                None,
            )
            if cancelled_booking is not None:
                failed_result = await session.execute(
                    select(Notification).where(
                        Notification.booking_id == cancelled_booking.id,
                        Notification.type == NotificationType.REMINDER_2H,
                        Notification.status == NotificationStatus.FAILED,
                    )
                )
                failed_item = failed_result.scalar_one_or_none()
                if failed_item is None:
                    session.add(
                        Notification(
                            booking_id=cancelled_booking.id,
                            type=NotificationType.REMINDER_2H,
                            scheduled_at=now_utc - timedelta(days=1),
                            status=NotificationStatus.FAILED,
                            attempts=4,
                            error="Demo failed delivery",
                        )
                    )
                    created += 1

        await session.commit()

    return created, updated


async def _ensure_audit_logs() -> tuple[int, int]:
    created = 0
    updated = 0
    report_date = (date.today() - timedelta(days=1)).isoformat()

    session_factory = get_session_factory()
    async with session_factory() as session:
        marker_result = await session.execute(
            select(AuditLog).where(
                AuditLog.entity_type == "seed",
                AuditLog.entity_id == "full_demo_v1",
                AuditLog.action == "completed",
            )
        )
        marker = marker_result.scalar_one_or_none()
        if marker is None:
            session.add(
                AuditLog(
                    actor_id=None,
                    entity_type="seed",
                    entity_id="full_demo_v1",
                    action="completed",
                    payload={"at": datetime.now(timezone.utc).isoformat()},
                )
            )
            created += 1
        else:
            marker.payload = {"at": datetime.now(timezone.utc).isoformat()}
            updated += 1

        report_result = await session.execute(
            select(AuditLog).where(
                AuditLog.entity_type == "manager_daily_report",
                AuditLog.entity_id == report_date,
                AuditLog.action == "sent",
            )
        )
        report_log = report_result.scalar_one_or_none()
        if report_log is None:
            session.add(
                AuditLog(
                    actor_id=None,
                    entity_type="manager_daily_report",
                    entity_id=report_date,
                    action="sent",
                    payload={"delivered_chats": 1, "source": "seed_full_demo"},
                )
            )
            created += 1
        else:
            report_log.payload = {"delivered_chats": 1, "source": "seed_full_demo"}
            updated += 1

        await session.commit()

    return created, updated


async def _print_counts() -> None:
    session_factory = get_session_factory()
    async with session_factory() as session:
        users_count = int(await session.scalar(select(func.count(User.id))) or 0)
        services_count = int(await session.scalar(select(func.count(Service.id))) or 0)
        working_hours_count = int(await session.scalar(select(func.count(WorkingHours.id))) or 0)
        bookings_count = await session.scalar(select(func.count(Booking.id)))
        waitlist_count = await session.scalar(select(func.count(WaitlistEntry.id)))
        notifications_count = await session.scalar(select(func.count(Notification.id)))
        audit_count = await session.scalar(select(func.count(AuditLog.id)))

        print("Current counts:")
        print(f"users={users_count}")
        print(f"services={services_count}")
        print(f"working_hours={working_hours_count}")
        print(f"bookings={int(bookings_count or 0)}")
        print(f"waitlist_entries={int(waitlist_count or 0)}")
        print(f"notifications={int(notifications_count or 0)}")
        print(f"audit_log={int(audit_count or 0)}")


async def main() -> None:
    service_created, service_updated = await upsert_services()
    hours_created, hours_updated = await upsert_working_hours()
    services_by_name = await _load_services()
    users_by_telegram, users_created, users_updated = await _ensure_users()
    bookings, bookings_created, bookings_updated = await _ensure_bookings(
        users_by_telegram=users_by_telegram,
        services_by_name=services_by_name,
    )
    waitlist_created, waitlist_updated = await _ensure_waitlist(
        users_by_telegram=users_by_telegram,
        services_by_name=services_by_name,
    )
    notifications_created, notifications_updated = await _ensure_notifications(bookings)
    audit_created, audit_updated = await _ensure_audit_logs()

    print(
        "Full demo seed complete: "
        f"services(created={service_created}, updated={service_updated}), "
        f"working_hours(created={hours_created}, updated={hours_updated}), "
        f"users(created={users_created}, updated={users_updated}), "
        f"bookings(created={bookings_created}, updated={bookings_updated}), "
        f"waitlist(created={waitlist_created}, updated={waitlist_updated}), "
        f"notifications(created={notifications_created}, updated={notifications_updated}), "
        f"audit(created={audit_created}, updated={audit_updated})"
    )

    await _print_counts()


if __name__ == "__main__":
    asyncio.run(main())
