from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from datetime import date, datetime, time as dt_time, timedelta, timezone
from uuid import UUID
from zoneinfo import ZoneInfo

from aiogram import Bot
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot.keyboards import build_reminder_confirmation_keyboard
from app.bot.localization import LOCALE_EN, normalize_locale
from app.infrastructure.config import Settings, get_settings
from app.infrastructure.db.enums import BookingStatus, NotificationStatus, NotificationType
from app.infrastructure.db.models import AuditLog, Booking, Notification, Service, User, WaitlistEntry
from app.infrastructure.db.session import get_session_factory
from app.infrastructure.logging import configure_logging

logger = logging.getLogger(__name__)

RETRY_DELAYS_MIN = (5, 15, 30)
DUE_BATCH_SIZE = 100
DAILY_REPORT_ENTITY_TYPE = "manager_daily_report"
DAILY_REPORT_ACTION = "sent"


@dataclass(frozen=True)
class NotificationPayload:
    booking: Booking
    client: User
    service: Service


@dataclass(frozen=True)
class DailyReportStats:
    report_date: date
    total: int
    new_count: int
    confirmed_count: int
    done_count: int
    cancelled_count: int
    no_show_count: int
    waitlist_count: int
    tomorrow_total: int
    tomorrow_active_count: int


def _parse_manager_chat_ids(raw: str) -> list[int]:
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


def _build_client_reminder_text(notification_type: NotificationType, payload: NotificationPayload) -> str:
    locale = normalize_locale(payload.client.locale)
    date_label = payload.booking.date.strftime("%d.%m.%Y")
    time_label = payload.booking.start_time.strftime("%H:%M")

    if locale == LOCALE_EN:
        if notification_type == NotificationType.REMINDER_24H:
            prefix = "⏰ Reminder: 24 hours left before your appointment."
        elif notification_type == NotificationType.REMINDER_2H:
            prefix = "⏰ Reminder: 2 hours left before your appointment."
        else:
            prefix = "⏰ Appointment reminder."
        return (
            f"{prefix}\n\n"
            f"🧾 Service: <b>{payload.service.name}</b>\n\n"
            f"📅 Date: <b>{date_label}</b>\n\n"
            f"🕒 Time: <b>{time_label}</b>\n\n"
            "Please confirm your visit:"
        )

    if notification_type == NotificationType.REMINDER_24H:
        prefix = "⏰ Напоминание: до вашей записи осталось 24 часа."
    elif notification_type == NotificationType.REMINDER_2H:
        prefix = "⏰ Напоминание: до вашей записи осталось 2 часа."
    else:
        prefix = "⏰ Напоминание по вашей записи."
    return (
        f"{prefix}\n\n"
        f"🧾 Услуга: <b>{payload.service.name}</b>\n\n"
        f"📅 Дата: <b>{date_label}</b>\n\n"
        f"🕒 Время: <b>{time_label}</b>\n\n"
        "Подтвердите, пожалуйста, визит:"
    )


def _build_manager_escalation_text(notification: Notification, reason: str, payload: NotificationPayload) -> str:
    return (
        "Эскалация: не удалось отправить напоминание клиенту.\n"
        f"Notification ID: <code>{notification.id}</code>\n"
        f"Booking ID: <code>{payload.booking.id}</code>\n"
        f"Услуга: <b>{payload.service.name}</b>\n"
        f"Клиент: <b>{payload.client.full_name or '-'}</b>\n"
        f"Телефон: <b>{payload.client.phone or '-'}</b>\n"
        f"Telegram ID: <code>{payload.client.telegram_id}</code>\n"
        f"Причина: <code>{reason}</code>"
    )


def _build_manager_alert_text(notification: Notification, payload: NotificationPayload) -> str:
    return (
        "Manager alert\n"
        f"Notification ID: <code>{notification.id}</code>\n"
        f"Booking ID: <code>{payload.booking.id}</code>\n"
        f"Услуга: <b>{payload.service.name}</b>\n"
        f"Клиент: <b>{payload.client.full_name or '-'}</b>\n"
        f"Телефон: <b>{payload.client.phone or '-'}</b>\n"
        f"Telegram ID: <code>{payload.client.telegram_id}</code>"
    )


def _should_send_daily_report_now(now_local: datetime, report_hour: int, report_minute: int) -> bool:
    planned_time = dt_time(hour=report_hour, minute=report_minute)
    current_time = now_local.time().replace(second=0, microsecond=0)
    return current_time >= planned_time


def _build_daily_report_text(stats: DailyReportStats, timezone_name: str) -> str:
    return (
        "📊 <b>Ежедневный отчёт</b>\n\n"
        f"🗓 Дата: <b>{stats.report_date.strftime('%d.%m.%Y')}</b>\n"
        f"🕰 Часовой пояс: <b>{timezone_name}</b>\n\n"
        f"🧾 Записей на сегодня: <b>{stats.total}</b>\n"
        f"• Новые: <b>{stats.new_count}</b>\n"
        f"• Подтверждённые: <b>{stats.confirmed_count}</b>\n"
        f"• Завершённые: <b>{stats.done_count}</b>\n"
        f"• Отменённые: <b>{stats.cancelled_count}</b>\n"
        f"• Не пришёл: <b>{stats.no_show_count}</b>\n\n"
        f"🕒 Лист ожидания на сегодня: <b>{stats.waitlist_count}</b>\n\n"
        f"📅 На завтра всего записей: <b>{stats.tomorrow_total}</b>\n"
        f"📌 На завтра активных (new/confirmed): <b>{stats.tomorrow_active_count}</b>"
    )


async def _is_daily_report_sent(
    session: AsyncSession,
    *,
    report_date: date,
) -> bool:
    result = await session.execute(
        select(AuditLog.id)
        .where(AuditLog.entity_type == DAILY_REPORT_ENTITY_TYPE)
        .where(AuditLog.entity_id == report_date.isoformat())
        .where(AuditLog.action == DAILY_REPORT_ACTION)
        .limit(1)
    )
    return result.scalar_one_or_none() is not None


async def _load_daily_report_stats(
    session: AsyncSession,
    *,
    report_date: date,
) -> DailyReportStats:
    today_result = await session.execute(
        select(
            func.count(Booking.id),
            func.count(Booking.id).filter(Booking.status == BookingStatus.NEW),
            func.count(Booking.id).filter(Booking.status == BookingStatus.CONFIRMED),
            func.count(Booking.id).filter(Booking.status == BookingStatus.DONE),
            func.count(Booking.id).filter(Booking.status == BookingStatus.CANCELLED),
            func.count(Booking.id).filter(Booking.status == BookingStatus.NO_SHOW),
        ).where(Booking.date == report_date)
    )
    today_row = today_result.one()
    total = int(today_row[0] or 0)
    new_count = int(today_row[1] or 0)
    confirmed_count = int(today_row[2] or 0)
    done_count = int(today_row[3] or 0)
    cancelled_count = int(today_row[4] or 0)
    no_show_count = int(today_row[5] or 0)

    waitlist_result = await session.execute(
        select(func.count(WaitlistEntry.id)).where(WaitlistEntry.date == report_date)
    )
    waitlist_count = int(waitlist_result.scalar_one() or 0)

    tomorrow_date = report_date + timedelta(days=1)
    tomorrow_result = await session.execute(
        select(
            func.count(Booking.id),
            func.count(Booking.id).filter(
                Booking.status.in_([BookingStatus.NEW, BookingStatus.CONFIRMED])
            ),
        ).where(Booking.date == tomorrow_date)
    )
    tomorrow_row = tomorrow_result.one()
    tomorrow_total = int(tomorrow_row[0] or 0)
    tomorrow_active_count = int(tomorrow_row[1] or 0)

    return DailyReportStats(
        report_date=report_date,
        total=total,
        new_count=new_count,
        confirmed_count=confirmed_count,
        done_count=done_count,
        cancelled_count=cancelled_count,
        no_show_count=no_show_count,
        waitlist_count=waitlist_count,
        tomorrow_total=tomorrow_total,
        tomorrow_active_count=tomorrow_active_count,
    )


async def _mark_daily_report_sent(
    session: AsyncSession,
    *,
    stats: DailyReportStats,
    timezone_name: str,
    delivered_chats: int,
) -> None:
    if await _is_daily_report_sent(session, report_date=stats.report_date):
        return

    session.add(
        AuditLog(
            actor_id=None,
            entity_type=DAILY_REPORT_ENTITY_TYPE,
            entity_id=stats.report_date.isoformat(),
            action=DAILY_REPORT_ACTION,
            payload={
                "timezone": timezone_name,
                "delivered_chats": delivered_chats,
                "total": stats.total,
                "new": stats.new_count,
                "confirmed": stats.confirmed_count,
                "done": stats.done_count,
                "cancelled": stats.cancelled_count,
                "no_show": stats.no_show_count,
                "waitlist": stats.waitlist_count,
                "tomorrow_total": stats.tomorrow_total,
                "tomorrow_active": stats.tomorrow_active_count,
            },
        )
    )
    await session.commit()


async def _try_send_daily_report_if_due(bot: Bot, settings: Settings) -> None:
    if not settings.worker_daily_report_enabled:
        return
    if not _parse_manager_chat_ids(settings.telegram_manager_chat_ids):
        return

    try:
        tz = ZoneInfo(settings.timezone)
    except Exception:
        logger.exception(
            "Failed to resolve timezone for daily report",
            extra={"timezone": settings.timezone},
        )
        return

    now_local = datetime.now(tz)
    if not _should_send_daily_report_now(
        now_local,
        settings.worker_daily_report_hour,
        settings.worker_daily_report_minute,
    ):
        return

    report_date = now_local.date()
    session_factory = get_session_factory()
    async with session_factory() as session:
        already_sent = await _is_daily_report_sent(session, report_date=report_date)
        if already_sent:
            return
        stats = await _load_daily_report_stats(session, report_date=report_date)

    report_text = _build_daily_report_text(stats, settings.timezone)
    delivered_chats = await _send_to_managers(bot, settings, report_text)
    if delivered_chats == 0:
        logger.warning(
            "Daily report was not delivered to any manager chats",
            extra={"report_date": report_date.isoformat()},
        )
        return

    async with session_factory() as session:
        await _mark_daily_report_sent(
            session,
            stats=stats,
            timezone_name=settings.timezone,
            delivered_chats=delivered_chats,
        )

async def _send_to_managers(bot: Bot, settings: Settings, text: str) -> int:
    manager_chat_ids = _parse_manager_chat_ids(settings.telegram_manager_chat_ids)
    if not manager_chat_ids:
        return 0

    sent_count = 0
    for chat_id in manager_chat_ids:
        try:
            await bot.send_message(chat_id=chat_id, text=text)
            sent_count += 1
        except Exception:
            logger.exception(
                "Failed to send message to manager",
                extra={"manager_chat_id": chat_id},
            )
    return sent_count


async def _get_due_notification_ids(session: AsyncSession) -> list[UUID]:
    now_utc = datetime.now(timezone.utc)
    result = await session.execute(
        select(Notification.id)
        .where(Notification.status == NotificationStatus.PENDING)
        .where(Notification.scheduled_at <= now_utc)
        .order_by(Notification.scheduled_at.asc())
        .limit(DUE_BATCH_SIZE)
    )
    return [row.id for row in result]


async def _load_payload(session: AsyncSession, notification: Notification) -> NotificationPayload | None:
    booking = await session.get(Booking, notification.booking_id)
    if booking is None:
        return None
    client = await session.get(User, booking.client_id)
    if client is None:
        return None
    service = await session.get(Service, booking.service_id)
    if service is None:
        return None
    return NotificationPayload(booking=booking, client=client, service=service)


def _is_terminal_booking_status(status: BookingStatus) -> bool:
    return status in {BookingStatus.CANCELLED, BookingStatus.DONE, BookingStatus.NO_SHOW}


def _failure_reason(exc: Exception) -> str:
    message = str(exc).strip()
    if not message:
        message = exc.__class__.__name__
    return message[:1000]


async def _mark_sent(session: AsyncSession, notification: Notification) -> None:
    notification.status = NotificationStatus.SENT
    notification.sent_at = datetime.now(timezone.utc)
    notification.error = None
    await session.commit()


async def _mark_failed_without_retry(
    session: AsyncSession,
    notification: Notification,
    reason: str,
) -> None:
    notification.attempts += 1
    notification.error = reason
    notification.status = NotificationStatus.FAILED
    await session.commit()


async def _handle_failure(
    session: AsyncSession,
    bot: Bot,
    settings: Settings,
    notification: Notification,
    payload: NotificationPayload | None,
    reason: str,
) -> None:
    notification.attempts += 1
    notification.error = reason

    if notification.attempts <= len(RETRY_DELAYS_MIN):
        delay_min = RETRY_DELAYS_MIN[notification.attempts - 1]
        notification.scheduled_at = datetime.now(timezone.utc) + timedelta(minutes=delay_min)
        notification.status = NotificationStatus.PENDING
        await session.commit()
        return

    notification.status = NotificationStatus.FAILED
    await session.commit()

    if payload is None:
        logger.warning(
            "Notification failed without payload context",
            extra={"notification_id": str(notification.id)},
        )
        return

    escalation_text = _build_manager_escalation_text(notification, reason, payload)
    await _send_to_managers(bot, settings, escalation_text)


async def _send_notification(
    bot: Bot,
    settings: Settings,
    notification: Notification,
    payload: NotificationPayload,
) -> None:
    if notification.type == NotificationType.MANAGER_ALERT:
        await _send_to_managers(bot, settings, _build_manager_alert_text(notification, payload))
        return

    reminder_text = _build_client_reminder_text(notification.type, payload)
    await bot.send_message(
        chat_id=payload.client.telegram_id,
        text=reminder_text,
        reply_markup=build_reminder_confirmation_keyboard(
            payload.booking.id,
            locale=normalize_locale(payload.client.locale),
        ),
    )


async def _process_notification_id(
    bot: Bot,
    settings: Settings,
    notification_id: UUID,
) -> None:
    session_factory = get_session_factory()
    async with session_factory() as session:
        notification = await session.get(Notification, notification_id)
        if notification is None:
            return

        if notification.status != NotificationStatus.PENDING:
            return
        if notification.scheduled_at > datetime.now(timezone.utc):
            return

        payload = await _load_payload(session, notification)
        if payload is None:
            await _handle_failure(
                session=session,
                bot=bot,
                settings=settings,
                notification=notification,
                payload=None,
                reason="Missing booking/client/service",
            )
            return

        if _is_terminal_booking_status(payload.booking.status):
            await _mark_failed_without_retry(
                session=session,
                notification=notification,
                reason=f"Booking status is {payload.booking.status.value}",
            )
            return

        try:
            await _send_notification(
                bot=bot,
                settings=settings,
                notification=notification,
                payload=payload,
            )
        except Exception as exc:
            await _handle_failure(
                session=session,
                bot=bot,
                settings=settings,
                notification=notification,
                payload=payload,
                reason=_failure_reason(exc),
            )
            return

        await _mark_sent(session, notification)


async def _run_worker() -> None:
    settings = get_settings()
    if not settings.telegram_bot_token or settings.telegram_bot_token == "replace_me":
        raise RuntimeError("TELEGRAM_BOT_TOKEN is not configured")

    poll_interval = max(settings.worker_poll_interval, 5)
    logger.info("Worker started", extra={"poll_interval_sec": poll_interval})

    bot = Bot(
        token=settings.telegram_bot_token,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    try:
        while True:
            session_factory = get_session_factory()
            async with session_factory() as session:
                due_notification_ids = await _get_due_notification_ids(session)

            if due_notification_ids:
                logger.info(
                    "Processing due notifications",
                    extra={"due_count": len(due_notification_ids)},
                )

            for notification_id in due_notification_ids:
                await _process_notification_id(bot, settings, notification_id)

            await _try_send_daily_report_if_due(bot, settings)
            await asyncio.sleep(poll_interval)
    finally:
        await bot.session.close()


def run() -> None:
    settings = get_settings()
    configure_logging(settings.log_level)
    asyncio.run(_run_worker())


if __name__ == "__main__":
    run()
