from __future__ import annotations

from datetime import date, time, timedelta
from types import SimpleNamespace

import pytest
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot.services.booking import (
    add_client_to_waitlist,
    cancel_booking_for_client,
    confirm_booking_by_reminder,
    create_booking_for_client,
    decline_booking_by_reminder,
    get_latest_client_booking_with_service,
    reschedule_booking_for_client,
    update_booking_status_by_admin,
)
from app.infrastructure.db.enums import BookingStatus, NotificationStatus
from app.infrastructure.db.models import Notification, Service, WaitlistEntry, WorkingHours


def _build_test_settings() -> SimpleNamespace:
    return SimpleNamespace(timezone="Europe/Moscow", slot_buffer_min=10)


@pytest.mark.asyncio
async def test_create_and_cancel_booking_updates_status_and_notifications(
    db_session: AsyncSession,
) -> None:
    service = Service(name="Integration Service", duration_min=60, price=1500.00, is_active=True)
    db_session.add(service)
    await db_session.commit()
    await db_session.refresh(service)

    booking_date = date.today() + timedelta(days=2)
    start = time(11, 0)

    booking = await create_booking_for_client(
        session=db_session,
        settings=_build_test_settings(),
        telegram_id=901001,
        full_name="Integration User",
        phone="+79990000001",
        service=service,
        booking_date=booking_date,
        start_time=start,
    )

    assert booking.status == BookingStatus.NEW

    notifications_result = await db_session.execute(
        select(func.count(Notification.id)).where(
            Notification.booking_id == booking.id,
            Notification.status == NotificationStatus.PENDING,
        )
    )
    assert int(notifications_result.scalar_one()) == 2

    cancelled_booking, was_cancelled = await cancel_booking_for_client(
        session=db_session,
        booking_id=booking.id,
        telegram_id=901001,
    )

    assert was_cancelled is True
    assert cancelled_booking is not None
    assert cancelled_booking.status == BookingStatus.CANCELLED


@pytest.mark.asyncio
async def test_create_booking_detects_slot_conflict(
    db_session: AsyncSession,
) -> None:
    service = Service(name="Conflict Service", duration_min=60, price=1900.00, is_active=True)
    db_session.add(service)
    await db_session.commit()
    await db_session.refresh(service)

    booking_date = date.today() + timedelta(days=2)
    start = time(12, 0)

    await create_booking_for_client(
        session=db_session,
        settings=_build_test_settings(),
        telegram_id=902001,
        full_name="User One",
        phone="+79990000002",
        service=service,
        booking_date=booking_date,
        start_time=start,
    )

    with pytest.raises(IntegrityError):
        await create_booking_for_client(
            session=db_session,
            settings=_build_test_settings(),
            telegram_id=902002,
            full_name="User Two",
            phone="+79990000003",
            service=service,
            booking_date=booking_date,
            start_time=start,
        )

    await db_session.rollback()


@pytest.mark.asyncio
async def test_reschedule_booking_recreates_pending_reminders(
    db_session: AsyncSession,
) -> None:
    service = Service(name="Reschedule Service", duration_min=60, price=2100.00, is_active=True)
    reschedule_date = date.today() + timedelta(days=5)
    working_hours = WorkingHours(
        weekday=reschedule_date.isoweekday(),
        start_time=time(9, 0),
        end_time=time(18, 0),
        is_working_day=True,
    )
    db_session.add(service)
    db_session.add(working_hours)
    await db_session.commit()
    await db_session.refresh(service)

    initial_date = date.today() + timedelta(days=3)
    booking = await create_booking_for_client(
        session=db_session,
        settings=_build_test_settings(),
        telegram_id=903001,
        full_name="Reschedule User",
        phone="+79990000004",
        service=service,
        booking_date=initial_date,
        start_time=time(11, 0),
    )

    before_ids_result = await db_session.execute(
        select(Notification.id).where(
            Notification.booking_id == booking.id,
            Notification.status == NotificationStatus.PENDING,
        )
    )
    before_ids = {row.id for row in before_ids_result}
    assert len(before_ids) == 2

    updated_booking, updated_service, error = await reschedule_booking_for_client(
        session=db_session,
        settings=_build_test_settings(),
        booking_id=booking.id,
        telegram_id=903001,
        new_date=reschedule_date,
        new_start_time=time(13, 40),
    )
    assert error is None
    assert updated_booking is not None
    assert updated_service is not None
    assert updated_booking.date == reschedule_date
    assert updated_booking.start_time == time(13, 40)
    assert updated_booking.status == BookingStatus.NEW

    after_ids_result = await db_session.execute(
        select(Notification.id).where(
            Notification.booking_id == booking.id,
            Notification.status == NotificationStatus.PENDING,
        )
    )
    after_ids = {row.id for row in after_ids_result}
    assert len(after_ids) == 2
    assert before_ids.isdisjoint(after_ids)


@pytest.mark.asyncio
async def test_reminder_confirm_then_decline_updates_status(
    db_session: AsyncSession,
) -> None:
    service = Service(name="Reminder Action Service", duration_min=60, price=1800.00, is_active=True)
    db_session.add(service)
    await db_session.commit()
    await db_session.refresh(service)

    booking = await create_booking_for_client(
        session=db_session,
        settings=_build_test_settings(),
        telegram_id=904001,
        full_name="Reminder User",
        phone="+79990000005",
        service=service,
        booking_date=date.today() + timedelta(days=3),
        start_time=time(12, 0),
    )

    confirmed_booking, was_confirmed, _ = await confirm_booking_by_reminder(
        session=db_session,
        booking_id=booking.id,
        telegram_id=904001,
    )
    assert was_confirmed is True
    assert confirmed_booking is not None
    assert confirmed_booking.status == BookingStatus.CONFIRMED

    confirmed_again, was_confirmed_again, _ = await confirm_booking_by_reminder(
        session=db_session,
        booking_id=booking.id,
        telegram_id=904001,
    )
    assert was_confirmed_again is False
    assert confirmed_again is not None
    assert confirmed_again.status == BookingStatus.CONFIRMED

    declined_booking, was_declined, _ = await decline_booking_by_reminder(
        session=db_session,
        booking_id=booking.id,
        telegram_id=904001,
    )
    assert was_declined is True
    assert declined_booking is not None
    assert declined_booking.status == BookingStatus.CANCELLED

    pending_result = await db_session.execute(
        select(func.count(Notification.id)).where(
            Notification.booking_id == booking.id,
            Notification.status == NotificationStatus.PENDING,
        )
    )
    assert int(pending_result.scalar_one()) == 0


@pytest.mark.asyncio
async def test_admin_status_transitions_confirm_done_and_no_show_rules(
    db_session: AsyncSession,
) -> None:
    service = Service(name="Admin Status Service", duration_min=60, price=2000.00, is_active=True)
    db_session.add(service)
    await db_session.commit()
    await db_session.refresh(service)

    booking = await create_booking_for_client(
        session=db_session,
        settings=_build_test_settings(),
        telegram_id=905001,
        full_name="Admin Status User",
        phone="+79990000006",
        service=service,
        booking_date=date.today() + timedelta(days=4),
        start_time=time(12, 0),
    )

    confirmed_booking, _, _, confirm_error = await update_booking_status_by_admin(
        session=db_session,
        booking_id=booking.id,
        target_status=BookingStatus.CONFIRMED,
        timezone_name=_build_test_settings().timezone,
    )
    assert confirm_error is None
    assert confirmed_booking is not None
    assert confirmed_booking.status == BookingStatus.CONFIRMED

    no_show_booking, _, _, no_show_error = await update_booking_status_by_admin(
        session=db_session,
        booking_id=booking.id,
        target_status=BookingStatus.NO_SHOW,
        timezone_name=_build_test_settings().timezone,
    )
    assert no_show_booking is not None
    assert no_show_booking.status == BookingStatus.CONFIRMED
    assert no_show_error == "No-show можно поставить только после времени визита."

    done_booking, _, _, done_error = await update_booking_status_by_admin(
        session=db_session,
        booking_id=booking.id,
        target_status=BookingStatus.DONE,
        timezone_name=_build_test_settings().timezone,
    )
    assert done_error is None
    assert done_booking is not None
    assert done_booking.status == BookingStatus.DONE


@pytest.mark.asyncio
async def test_waitlist_add_and_prevent_duplicate_entries(
    db_session: AsyncSession,
) -> None:
    service = Service(name="Waitlist Service", duration_min=45, price=1300.00, is_active=True)
    db_session.add(service)
    await db_session.commit()
    await db_session.refresh(service)

    wait_date = date.today() + timedelta(days=2)
    entry, created, error = await add_client_to_waitlist(
        session=db_session,
        telegram_id=906001,
        full_name="Waitlist Client",
        service_id=service.id,
        wait_date=wait_date,
    )
    assert error is None
    assert created is True
    assert entry is not None

    duplicate_entry, duplicate_created, duplicate_error = await add_client_to_waitlist(
        session=db_session,
        telegram_id=906001,
        full_name="Waitlist Client",
        service_id=service.id,
        wait_date=wait_date,
    )
    assert duplicate_error is None
    assert duplicate_created is False
    assert duplicate_entry is not None
    assert duplicate_entry.id == entry.id

    count_result = await db_session.execute(
        select(func.count(WaitlistEntry.id)).where(
            WaitlistEntry.service_id == service.id,
            WaitlistEntry.date == wait_date,
        )
    )
    assert int(count_result.scalar_one()) == 1


@pytest.mark.asyncio
async def test_get_latest_client_booking_with_service_uses_last_booking_as_template(
    db_session: AsyncSession,
) -> None:
    service_old = Service(name="Template Old", duration_min=45, price=1000.00, is_active=True)
    service_new = Service(name="Template New", duration_min=60, price=1800.00, is_active=True)
    db_session.add(service_old)
    db_session.add(service_new)
    await db_session.commit()
    await db_session.refresh(service_old)
    await db_session.refresh(service_new)

    await create_booking_for_client(
        session=db_session,
        settings=_build_test_settings(),
        telegram_id=907001,
        full_name="Template User",
        phone="+79990000007",
        service=service_old,
        booking_date=date.today() + timedelta(days=3),
        start_time=time(10, 0),
    )
    booking_latest = await create_booking_for_client(
        session=db_session,
        settings=_build_test_settings(),
        telegram_id=907001,
        full_name="Template User",
        phone="+79990000007",
        service=service_new,
        booking_date=date.today() + timedelta(days=5),
        start_time=time(14, 0),
    )

    user, booking, service = await get_latest_client_booking_with_service(
        db_session,
        telegram_id=907001,
    )
    assert user is not None
    assert booking is not None
    assert service is not None
    assert booking.id == booking_latest.id
    assert service.id == service_new.id
