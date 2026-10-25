from __future__ import annotations

import logging
import re
from datetime import date, datetime, time
from decimal import Decimal, InvalidOperation
from html import escape
from typing import Optional
from uuid import UUID

from aiogram import F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from sqlalchemy.exc import IntegrityError

from app.bot.keyboards import (
    build_booking_actions_keyboard,
    build_cancel_confirmation_keyboard,
    build_confirmation_keyboard,
    build_dates_keyboard,
    build_reschedule_dates_keyboard,
    build_reschedule_slots_keyboard,
    build_services_keyboard,
    build_slots_keyboard,
    build_waitlist_offer_keyboard,
    get_language_picker_keyboard,
)
from app.bot.localization import (
    DEFAULT_LOCALE,
    LOCALE_EN,
    LOCALE_RU,
    MAIN_MENU_TEXT_MATCHES,
    booking_status_label,
    normalize_locale,
)
from app.bot.keyboards.main import get_main_menu
from app.bot.services import (
    add_client_to_waitlist,
    build_candidate_dates,
    cancel_booking_for_client,
    confirm_booking_by_reminder,
    create_service_by_admin,
    create_booking_for_client,
    deactivate_service_by_admin,
    delete_working_hours_by_admin,
    decline_booking_by_reminder,
    get_client_booking_with_service,
    get_latest_client_booking_with_service,
    get_or_create_client_profile,
    get_service,
    get_slots_for_service_date,
    get_user_locale,
    get_working_weekdays,
    list_active_services,
    list_client_bookings,
    list_services_for_admin,
    list_working_hours_for_admin,
    parse_manager_chat_ids,
    reschedule_booking_for_client,
    set_working_day_off_by_admin,
    set_working_hours_for_admin,
    update_booking_status_by_admin,
    update_service_by_admin,
)
from app.bot.states.booking import BookingStates
from app.application.use_cases.validation import normalize_phone_ru, validate_full_name
from app.infrastructure.config import get_settings
from app.infrastructure.db.enums import BookingStatus
from app.infrastructure.db.models import Booking, Service, User, WaitlistEntry
from app.infrastructure.db.session import get_session_factory

router = Router()
logger = logging.getLogger(__name__)

UUID_PATTERN = re.compile(
    r"\b[0-9a-fA-F]{8}-"
    r"[0-9a-fA-F]{4}-"
    r"[0-9a-fA-F]{4}-"
    r"[0-9a-fA-F]{4}-"
    r"[0-9a-fA-F]{12}\b"
)

WEEKDAY_LABELS_RU: dict[int, str] = {
    1: "Пн",
    2: "Вт",
    3: "Ср",
    4: "Чт",
    5: "Пт",
    6: "Сб",
    7: "Вс",
}

ADMIN_CHANNEL_COMMANDS = {
    "admin_help",
    "admin_cancel",
    "admin_confirm",
    "admin_done",
    "admin_noshow",
    "admin_services",
    "admin_service_add",
    "admin_service_edit",
    "admin_service_delete",
    "admin_hours",
    "admin_hours_set",
    "admin_hours_off",
    "admin_hours_delete",
}

BOOK_MENU_TEXTS = tuple(sorted(MAIN_MENU_TEXT_MATCHES["book"]))
QUICK_MENU_TEXTS = tuple(sorted(MAIN_MENU_TEXT_MATCHES["quick"]))
MY_BOOKINGS_MENU_TEXTS = tuple(sorted(MAIN_MENU_TEXT_MATCHES["my_bookings"]))
CANCEL_MENU_TEXTS = tuple(sorted(MAIN_MENU_TEXT_MATCHES["cancel"]))
LANGUAGE_MENU_TEXTS = tuple(sorted(MAIN_MENU_TEXT_MATCHES["language"]))

ERROR_TRANSLATIONS_EN = {
    "Услуга недоступна.": "Service unavailable.",
    "Не удалось добавить в лист ожидания.": "Could not add you to the waitlist.",
    "Нельзя записаться на прошедшее время.": "You cannot book a past time slot.",
    "Запись не найдена.": "Booking not found.",
    "Услуга недоступна для переноса.": "Service unavailable for rescheduling.",
    "Эту запись уже нельзя перенести.": "This booking can no longer be rescheduled.",
    "Вы выбрали текущие дату и время.": "You selected the same date and time.",
    "Этот слот уже недоступен. Выберите другой.": "This slot is not available anymore. Choose another one.",
    "Этот слот только что заняли. Выберите другой.": "This slot has just been taken. Choose another one.",
    "Запись уже подтверждена.": "Booking is already confirmed.",
    "Эту запись уже нельзя подтвердить.": "This booking can no longer be confirmed.",
    "Отлично, визит подтверждён.": "Great, your visit is confirmed.",
    "Запись уже отменена.": "Booking is already cancelled.",
    "Эту запись уже нельзя отменить.": "This booking can no longer be cancelled.",
    "Поняли, запись отменена.": "Understood, booking cancelled.",
}


def _t(locale: str, ru_text: str, en_text: str) -> str:
    return en_text if normalize_locale(locale) == LOCALE_EN else ru_text


def _translate_error_text(locale: str, detail: str) -> str:
    if normalize_locale(locale) != LOCALE_EN:
        return detail
    return ERROR_TRANSLATIONS_EN.get(detail, detail)


def _status_label(status: BookingStatus, locale: str) -> str:
    return booking_status_label(status, normalize_locale(locale))


def _status_label_ru(status: BookingStatus) -> str:
    return _status_label(status, LOCALE_RU)


async def _resolve_locale(state: FSMContext | None, telegram_id: int | None) -> str:
    if state is not None:
        data = await state.get_data()
        if "locale" in data:
            return normalize_locale(str(data.get("locale")))

    if telegram_id is None:
        return DEFAULT_LOCALE

    session_factory = get_session_factory()
    async with session_factory() as session:
        stored_locale = await get_user_locale(session, telegram_id)
    locale = normalize_locale(stored_locale)

    if state is not None:
        await state.update_data(locale=locale)
    return locale


async def _save_locale(telegram_id: int, full_name: str, locale: str) -> None:
    normalized_locale = normalize_locale(locale)
    session_factory = get_session_factory()
    async with session_factory() as session:
        await get_or_create_client_profile(
            session=session,
            telegram_id=telegram_id,
            full_name=full_name,
            locale=normalized_locale,
        )
        await session.commit()


def _spaced(*lines: str) -> str:
    return "\n\n".join([line for line in lines if line.strip()])


async def _safe_edit(callback: CallbackQuery, text: str, **kwargs: object) -> None:
    if callback.message is None:
        return
    try:
        await callback.message.edit_text(text, **kwargs)
    except TelegramBadRequest:
        await callback.message.answer(text, **kwargs)


async def _send_visual(
    message: Message,
    *,
    sticker_id: str,
    fallback_dice: str = "🎯",
) -> None:
    if sticker_id:
        try:
            await message.answer_sticker(sticker=sticker_id)
            return
        except Exception:
            logger.exception("Failed to send sticker", extra={"sticker_id": sticker_id})

    try:
        await message.answer_dice(emoji=fallback_dice)
    except Exception:
        logger.exception("Failed to send fallback dice", extra={"emoji": fallback_dice})


def _parse_service_id(raw_data: str) -> Optional[UUID]:
    try:
        return UUID(raw_data.split(":", maxsplit=1)[1])
    except (IndexError, ValueError):
        return None


def _parse_selected_date(raw_data: str) -> Optional[date]:
    try:
        return date.fromisoformat(raw_data.split(":", maxsplit=1)[1])
    except (IndexError, ValueError):
        return None


def _parse_slot_time(raw: str) -> Optional[time]:
    try:
        return datetime.strptime(raw, "%H:%M").time()
    except ValueError:
        return None


def _parse_booking_id(raw_data: str, prefix: str) -> Optional[UUID]:
    if not raw_data.startswith(prefix):
        return None
    try:
        return UUID(raw_data.split(":", maxsplit=1)[1])
    except (IndexError, ValueError):
        return None


def _parse_date_with_prefix(raw_data: str, prefix: str) -> Optional[date]:
    if not raw_data.startswith(prefix):
        return None
    try:
        return date.fromisoformat(raw_data.split(":", maxsplit=1)[1])
    except (IndexError, ValueError):
        return None


def _parse_time_with_prefix(raw_data: str, prefix: str) -> Optional[time]:
    if not raw_data.startswith(prefix):
        return None
    try:
        raw_value = raw_data.split(":", maxsplit=1)[1]
    except IndexError:
        return None
    return _parse_slot_time(raw_value)


def _extract_booking_id_from_text(raw_text: str) -> Optional[UUID]:
    match = UUID_PATTERN.search(raw_text)
    if match is None:
        return None
    try:
        return UUID(match.group(0))
    except ValueError:
        return None


def _is_command(text: str, command: str) -> bool:
    if not text.strip().startswith("/"):
        return False
    first_token = text.strip().split(maxsplit=1)[0].lower()
    return first_token == f"/{command}" or first_token.startswith(f"/{command}@")


def _extract_command_name(text: str) -> Optional[str]:
    stripped = text.strip()
    if not stripped.startswith("/"):
        return None
    first_token = stripped.split(maxsplit=1)[0].lower()
    command = first_token[1:]
    if "@" in command:
        command = command.split("@", maxsplit=1)[0]
    return command or None


def _get_command_body(text: str) -> str:
    parts = text.strip().split(maxsplit=1)
    return parts[1].strip() if len(parts) > 1 else ""


def _parse_admin_cancel_command(
    text: str,
    reply_text: str | None,
) -> tuple[Optional[UUID], Optional[str], Optional[str]]:
    if not _is_command(text, "admin_cancel"):
        return None, None, "Это не команда /admin_cancel."

    parts = text.strip().split(maxsplit=1)
    body = parts[1].strip() if len(parts) > 1 else ""

    booking_id: Optional[UUID] = None
    reason: str = ""

    if body:
        if "|" in body:
            left_part, right_part = body.split("|", maxsplit=1)
            booking_id = _extract_booking_id_from_text(left_part)
            reason = right_part.strip()
        else:
            booking_id_match = UUID_PATTERN.search(body)
            if booking_id_match is None:
                reason = body
            else:
                try:
                    booking_id = UUID(booking_id_match.group(0))
                except ValueError:
                    booking_id = None
                    reason = body
                else:
                    without_id = f"{body[:booking_id_match.start()]} {body[booking_id_match.end():]}"
                    reason = without_id.strip(" -|\n\t")

    if booking_id is None and reply_text:
        booking_id = _extract_booking_id_from_text(reply_text)

    if booking_id is None:
        return None, None, "Не найден ID записи. Укажите его в команде или ответьте на карточку записи."

    if len(reason.strip()) < 3:
        return None, None, "Укажите причину отмены (минимум 3 символа)."

    return booking_id, reason.strip(), None


def _parse_admin_status_command(
    *,
    text: str,
    reply_text: str | None,
    command: str,
) -> tuple[Optional[UUID], Optional[str]]:
    if not _is_command(text, command):
        return None, f"Это не команда /{command}."

    body = _get_command_body(text)
    booking_id = _extract_booking_id_from_text(body) if body else None
    if booking_id is None and reply_text:
        booking_id = _extract_booking_id_from_text(reply_text)
    if booking_id is None:
        return None, "Не найден ID записи. Укажите ID или ответьте на карточку записи."
    return booking_id, None


def _parse_price(raw: str) -> tuple[Optional[Decimal], Optional[str]]:
    cleaned = raw.strip().replace(",", ".")
    if cleaned in {"-", "none", "null", ""}:
        return None, None
    try:
        value = Decimal(cleaned)
    except InvalidOperation:
        return None, "Некорректная цена."
    if value < 0:
        return None, "Цена не может быть отрицательной."
    return value.quantize(Decimal("0.01")), None


def _parse_service_add_command(
    text: str,
) -> tuple[Optional[str], Optional[int], Optional[Decimal], Optional[str]]:
    if not _is_command(text, "admin_service_add"):
        return None, None, None, "Это не команда /admin_service_add."

    body = _get_command_body(text)
    parts = [part.strip() for part in body.split("|")]
    if len(parts) != 3:
        return None, None, None, "Формат: /admin_service_add <название> | <минуты> | <цена|->"

    name = parts[0]
    if len(name) < 2 or len(name) > 120:
        return None, None, None, "Название услуги: от 2 до 120 символов."

    try:
        duration_min = int(parts[1])
    except ValueError:
        return None, None, None, "Длительность должна быть числом (в минутах)."
    if duration_min < 5 or duration_min > 480:
        return None, None, None, "Длительность должна быть в диапазоне 5-480 минут."

    price, price_error = _parse_price(parts[2])
    if price_error:
        return None, None, None, price_error

    return name, duration_min, price, None


def _parse_bool_value(raw: str) -> tuple[Optional[bool], Optional[str]]:
    value = raw.strip().lower()
    if value in {"1", "true", "on", "yes", "да", "активна"}:
        return True, None
    if value in {"0", "false", "off", "no", "нет", "неактивна"}:
        return False, None
    return None, "Активность укажите как 1/0 (или true/false)."


def _parse_service_edit_command(
    text: str,
) -> tuple[Optional[UUID], Optional[str], Optional[int], Optional[Decimal], Optional[bool], Optional[str]]:
    if not _is_command(text, "admin_service_edit"):
        return None, None, None, None, None, "Это не команда /admin_service_edit."

    body = _get_command_body(text)
    parts = [part.strip() for part in body.split("|")]
    if len(parts) != 5:
        return None, None, None, None, None, (
            "Формат: /admin_service_edit <service_id> | <название> | <минуты> | <цена|-> | <1|0>"
        )

    try:
        service_id = UUID(parts[0])
    except ValueError:
        return None, None, None, None, None, "Некорректный service_id."

    name = parts[1]
    if len(name) < 2 or len(name) > 120:
        return None, None, None, None, None, "Название услуги: от 2 до 120 символов."

    try:
        duration_min = int(parts[2])
    except ValueError:
        return None, None, None, None, None, "Длительность должна быть числом."
    if duration_min < 5 or duration_min > 480:
        return None, None, None, None, None, "Длительность должна быть в диапазоне 5-480 минут."

    price, price_error = _parse_price(parts[3])
    if price_error:
        return None, None, None, None, None, price_error

    is_active, bool_error = _parse_bool_value(parts[4])
    if bool_error:
        return None, None, None, None, None, bool_error

    return service_id, name, duration_min, price, is_active, None


def _parse_service_delete_command(text: str) -> tuple[Optional[UUID], Optional[str]]:
    if not _is_command(text, "admin_service_delete"):
        return None, "Это не команда /admin_service_delete."
    body = _get_command_body(text)
    if not body:
        return None, "Укажите service_id: /admin_service_delete <service_id>"
    try:
        service_id = UUID(body.split(maxsplit=1)[0])
    except ValueError:
        return None, "Некорректный service_id."
    return service_id, None


def _parse_weekday(raw: str) -> Optional[int]:
    value = raw.strip().lower()
    by_alias = {
        "1": 1,
        "пн": 1,
        "понедельник": 1,
        "mon": 1,
        "2": 2,
        "вт": 2,
        "вторник": 2,
        "tue": 2,
        "3": 3,
        "ср": 3,
        "среда": 3,
        "wed": 3,
        "4": 4,
        "чт": 4,
        "четверг": 4,
        "thu": 4,
        "5": 5,
        "пт": 5,
        "пятница": 5,
        "fri": 5,
        "6": 6,
        "сб": 6,
        "суббота": 6,
        "sat": 6,
        "7": 7,
        "вс": 7,
        "воскресенье": 7,
        "sun": 7,
    }
    return by_alias.get(value)


def _parse_admin_hours_set_command(
    text: str,
) -> tuple[Optional[int], Optional[time], Optional[time], Optional[str]]:
    if not _is_command(text, "admin_hours_set"):
        return None, None, None, "Это не команда /admin_hours_set."

    body = _get_command_body(text)
    parts = [part.strip() for part in body.split("|")]
    if len(parts) != 3:
        return None, None, None, "Формат: /admin_hours_set <день> | <HH:MM> | <HH:MM>"

    weekday = _parse_weekday(parts[0])
    if weekday is None:
        return None, None, None, "Некорректный день недели. Используйте 1-7 или Пн/Вт..."

    start_time = _parse_slot_time(parts[1])
    end_time = _parse_slot_time(parts[2])
    if start_time is None or end_time is None:
        return None, None, None, "Время укажите в формате HH:MM."
    if start_time >= end_time:
        return None, None, None, "Начало смены должно быть раньше окончания."

    return weekday, start_time, end_time, None


def _parse_admin_hours_day_command(text: str, command: str) -> tuple[Optional[int], Optional[str]]:
    if not _is_command(text, command):
        return None, f"Это не команда /{command}."
    body = _get_command_body(text)
    if not body:
        return None, f"Укажите день недели: /{command} <день>"

    weekday = _parse_weekday(body.split(maxsplit=1)[0])
    if weekday is None:
        return None, "Некорректный день недели. Используйте 1-7 или Пн/Вт..."
    return weekday, None


def _admin_help_text() -> str:
    return _spaced(
        "🛠 <b>Команды администратора канала</b>",
        "<b>Справка:</b>\n<code>/admin_help</code>",
        (
            "<b>Статусы записи:</b>\n"
            "<code>/admin_confirm &lt;booking_id&gt;</code>\n"
            "<code>/admin_done &lt;booking_id&gt;</code>\n"
            "<code>/admin_noshow &lt;booking_id&gt;</code>"
        ),
        (
            "<b>Отмена записи:</b>\n"
            "<code>/admin_cancel &lt;booking_id&gt; | &lt;причина&gt;</code>"
        ),
        (
            "<b>Удобный вариант:</b>\n"
            "ответьте на пост с карточкой записи и отправьте:\n"
            "<code>/admin_cancel &lt;причина&gt;</code>"
        ),
        (
            "<b>Также через reply на карточку:</b>\n"
            "<code>/admin_confirm</code>\n"
            "<code>/admin_done</code>\n"
            "<code>/admin_noshow</code>"
        ),
        (
            "<b>Можно и в 2 строки:</b>\n"
            "<code>/admin_cancel\n"
            "Мастер заболел, перенос на завтра</code>"
        ),
        (
            "<b>Услуги:</b>\n"
            "<code>/admin_services</code>\n"
            "<code>/admin_service_add Название | 60 | 2500</code>\n"
            "<code>/admin_service_edit &lt;service_id&gt; | Название | 60 | 2500 | 1</code>\n"
            "<code>/admin_service_delete &lt;service_id&gt;</code>"
        ),
        (
            "<b>Календарь/время:</b>\n"
            "<code>/admin_hours</code>\n"
            "<code>/admin_hours_set Пн | 09:00 | 18:00</code>\n"
            "<code>/admin_hours_off Вс</code>\n"
            "<code>/admin_hours_delete Вс</code>"
        ),
    )


def _format_client_admin_cancelled_message(
    *,
    service_name: str,
    booking_date: date,
    start_time: time,
    reason: str,
    locale: str,
) -> str:
    lang = normalize_locale(locale)
    safe_service_name = escape(service_name)
    safe_reason = escape(reason)
    return _spaced(
        _t(
            lang,
            "❌ <b>Ваша запись отменена администратором</b>",
            "❌ <b>Your booking was cancelled by the administrator</b>",
        ),
        _t(lang, f"🧾 Услуга: <b>{safe_service_name}</b>", f"🧾 Service: <b>{safe_service_name}</b>"),
        _t(lang, f"📅 Дата: <b>{booking_date.strftime('%d.%m.%Y')}</b>", f"📅 Date: <b>{booking_date.strftime('%d.%m.%Y')}</b>"),
        _t(lang, f"🕒 Время: <b>{start_time.strftime('%H:%M')}</b>", f"🕒 Time: <b>{start_time.strftime('%H:%M')}</b>"),
        _t(lang, f"📝 Причина: <b>{safe_reason}</b>", f"📝 Reason: <b>{safe_reason}</b>"),
        _t(
            lang,
            "Для новой записи нажмите <b>«✨ Записаться»</b>.",
            "To create a new booking, tap <b>“✨ Book now”</b>.",
        ),
    )


def _format_admin_cancel_result_message(
    *,
    booking_id: UUID,
    service_name: str,
    booking_date: date,
    start_time: time,
    client_name: str,
    reason: str,
) -> str:
    safe_service_name = escape(service_name)
    safe_client_name = escape(client_name)
    safe_reason = escape(reason)
    return _spaced(
        "✅ <b>Запись отменена администратором</b>",
        f"ID: <code>{booking_id}</code>",
        f"🧾 Услуга: <b>{safe_service_name}</b>",
        f"📅 Дата: <b>{booking_date.strftime('%d.%m.%Y')}</b>",
        f"🕒 Время: <b>{start_time.strftime('%H:%M')}</b>",
        f"👤 Клиент: <b>{safe_client_name}</b>",
        f"📝 Причина: <b>{safe_reason}</b>",
    )


def _format_client_status_message(
    *,
    service_name: str,
    booking_date: date,
    start_time: time,
    status: BookingStatus,
    locale: str,
) -> str:
    lang = normalize_locale(locale)
    safe_service_name = escape(service_name)
    status_label = _status_label(status, lang)
    title_map_ru = {
        BookingStatus.CONFIRMED: "✅ <b>Ваша запись подтверждена администратором</b>",
        BookingStatus.DONE: "✅ <b>Визит отмечен как завершённый</b>",
        BookingStatus.NO_SHOW: "⚠️ <b>По записи отмечен статус «Клиент не пришёл»</b>",
    }
    title_map_en = {
        BookingStatus.CONFIRMED: "✅ <b>Your booking was confirmed by the administrator</b>",
        BookingStatus.DONE: "✅ <b>Your visit was marked as completed</b>",
        BookingStatus.NO_SHOW: "⚠️ <b>This booking was marked as no-show</b>",
    }
    title = (
        title_map_en.get(status, "ℹ️ <b>Booking status updated</b>")
        if lang == LOCALE_EN
        else title_map_ru.get(status, "ℹ️ <b>Статус записи обновлён</b>")
    )
    return _spaced(
        title,
        _t(lang, f"🧾 Услуга: <b>{safe_service_name}</b>", f"🧾 Service: <b>{safe_service_name}</b>"),
        _t(lang, f"📅 Дата: <b>{booking_date.strftime('%d.%m.%Y')}</b>", f"📅 Date: <b>{booking_date.strftime('%d.%m.%Y')}</b>"),
        _t(lang, f"🕒 Время: <b>{start_time.strftime('%H:%M')}</b>", f"🕒 Time: <b>{start_time.strftime('%H:%M')}</b>"),
        _t(lang, f"📌 Статус: <b>{status_label}</b>", f"📌 Status: <b>{status_label}</b>"),
    )


def _format_admin_status_result_message(
    *,
    booking_id: UUID,
    service_name: str,
    booking_date: date,
    start_time: time,
    client_name: str,
    status: BookingStatus,
) -> str:
    safe_service_name = escape(service_name)
    safe_client_name = escape(client_name)
    return _spaced(
        "✅ <b>Статус записи обновлён</b>",
        f"ID: <code>{booking_id}</code>",
        f"🧾 Услуга: <b>{safe_service_name}</b>",
        f"📅 Дата: <b>{booking_date.strftime('%d.%m.%Y')}</b>",
        f"🕒 Время: <b>{start_time.strftime('%H:%M')}</b>",
        f"👤 Клиент: <b>{safe_client_name}</b>",
        f"📌 Новый статус: <b>{_status_label_ru(status)}</b>",
    )


def _weekday_label(weekday: int) -> str:
    return WEEKDAY_LABELS_RU.get(weekday, f"День {weekday}")


async def _cancel_booking_by_admin(
    *,
    booking_id: UUID,
    reason: str,
) -> tuple[Optional[Booking], Optional[Service], Optional[User], Optional[str]]:
    session_factory = get_session_factory()
    async with session_factory() as session:
        booking = await session.get(Booking, booking_id)
        if booking is None:
            return None, None, None, "Запись не найдена."

        if booking.status == BookingStatus.CANCELLED:
            return booking, None, None, "Запись уже отменена."
        if booking.status in {BookingStatus.DONE, BookingStatus.NO_SHOW}:
            return booking, None, None, "Эту запись уже нельзя отменить."

        reason_comment = f"[ADMIN_CANCEL_REASON] {reason}"
        old_comment = (booking.comment or "").strip()
        booking.comment = reason_comment if not old_comment else f"{old_comment}\n\n{reason_comment}"
        booking.status = BookingStatus.CANCELLED
        await session.commit()
        await session.refresh(booking)

        service = await session.get(Service, booking.service_id)
        client = await session.get(User, booking.client_id)
        return booking, service, client, None


async def _safe_delete_channel_command(message: Message) -> None:
    try:
        await message.delete()
    except Exception:
        logger.exception("Failed to delete admin command message", extra={"chat_id": message.chat.id})


def _extract_reply_text(message: Message | None) -> Optional[str]:
    if message is None:
        return None

    text = (message.text or message.caption or "").strip()
    return text or None


def _is_manager_chat(chat_id: int) -> bool:
    settings = get_settings()
    manager_chat_ids = parse_manager_chat_ids(settings.telegram_manager_chat_ids)
    return chat_id in manager_chat_ids


def _format_new_booking_manager_message(
    booking_id: UUID,
    service_name: str,
    booking_date: date,
    start_time: time,
    client_name: str,
    client_phone: str,
    telegram_id: int,
) -> str:
    return _spaced(
        "🆕 Новая запись",
        f"ID: <code>{booking_id}</code>",
        f"🧾 Услуга: <b>{service_name}</b>",
        f"📅 Дата: <b>{booking_date.strftime('%d.%m.%Y')}</b>",
        f"🕒 Время: <b>{start_time.strftime('%H:%M')}</b>",
        f"👤 Клиент: <b>{client_name}</b>",
        f"📱 Телефон: <b>{client_phone}</b>",
        f"Telegram ID: <code>{telegram_id}</code>",
    )


def _format_cancelled_booking_manager_message(
    booking_id: UUID,
    service_name: str,
    booking_date: date,
    start_time: time,
    client_name: str,
    client_phone: str,
    telegram_id: int,
) -> str:
    return _spaced(
        "❌ Отмена записи",
        f"ID: <code>{booking_id}</code>",
        f"🧾 Услуга: <b>{service_name}</b>",
        f"📅 Дата: <b>{booking_date.strftime('%d.%m.%Y')}</b>",
        f"🕒 Время: <b>{start_time.strftime('%H:%M')}</b>",
        f"👤 Клиент: <b>{client_name}</b>",
        f"📱 Телефон: <b>{client_phone}</b>",
        f"Telegram ID: <code>{telegram_id}</code>",
        f"Статус: <b>{_status_label_ru(BookingStatus.CANCELLED)}</b>",
    )


def _format_rescheduled_booking_manager_message(
    *,
    booking_id: UUID,
    service_name: str,
    old_date: date,
    old_start_time: time,
    new_date: date,
    new_start_time: time,
    client_name: str,
    client_phone: str,
    telegram_id: int,
) -> str:
    return _spaced(
        "🔁 Клиент перенёс запись",
        f"ID: <code>{booking_id}</code>",
        f"🧾 Услуга: <b>{service_name}</b>",
        f"📆 Было: <b>{old_date.strftime('%d.%m.%Y')} {old_start_time.strftime('%H:%M')}</b>",
        f"📅 Стало: <b>{new_date.strftime('%d.%m.%Y')} {new_start_time.strftime('%H:%M')}</b>",
        f"👤 Клиент: <b>{client_name}</b>",
        f"📱 Телефон: <b>{client_phone}</b>",
        f"Telegram ID: <code>{telegram_id}</code>",
        f"Статус: <b>{_status_label_ru(BookingStatus.NEW)}</b>",
    )


def _format_waitlist_manager_message(
    *,
    waitlist_entry: WaitlistEntry,
    service_name: str,
    wait_date: date,
    client_name: str,
    client_phone: str,
    telegram_id: int,
) -> str:
    return _spaced(
        "🕒 Заявка в лист ожидания",
        f"ID заявки: <code>{waitlist_entry.id}</code>",
        f"🧾 Услуга: <b>{escape(service_name)}</b>",
        f"📅 Дата: <b>{wait_date.strftime('%d.%m.%Y')}</b>",
        f"👤 Клиент: <b>{escape(client_name)}</b>",
        f"📱 Телефон: <b>{escape(client_phone)}</b>",
        f"Telegram ID: <code>{telegram_id}</code>",
    )


def _format_booking_preview_message(
    *,
    service_name: str,
    selected_date_label: str,
    selected_slot: str,
    client_name: str,
    client_phone: str,
    locale: str,
    quick_mode: bool = False,
) -> str:
    lang = normalize_locale(locale)
    title = (
        _t(lang, "⚡ <b>Быстрая запись</b>", "⚡ <b>Quick booking</b>")
        if quick_mode
        else _t(lang, "✅ <b>Почти готово!</b>", "✅ <b>Almost done!</b>")
    )
    return _spaced(
        title,
        _t(lang, "Проверьте данные записи:", "Please review your booking details:"),
        _t(lang, f"• Услуга: <b>{service_name}</b>", f"• Service: <b>{service_name}</b>"),
        _t(lang, f"• Дата: <b>{selected_date_label}</b>", f"• Date: <b>{selected_date_label}</b>"),
        _t(lang, f"• Время: <b>{selected_slot}</b>", f"• Time: <b>{selected_slot}</b>"),
        _t(lang, f"• Имя: <b>{client_name}</b>", f"• Name: <b>{client_name}</b>"),
        _t(lang, f"• Телефон: <b>{client_phone}</b>", f"• Phone: <b>{client_phone}</b>"),
        _t(
            lang,
            "Если всё верно, нажмите <b>«✅ Подтвердить запись»</b>.",
            "If everything is correct, tap <b>“✅ Confirm booking”</b>.",
        ),
    )


def _format_admin_services_list_message(services: list[Service]) -> str:
    if not services:
        return _spaced("🧾 <b>Список услуг пуст.</b>", "Добавьте первую услугу через /admin_service_add.")

    lines: list[str] = []
    for service in services:
        active_label = "Активна" if service.is_active else "Неактивна"
        price_label = "-" if service.price is None else f"{service.price:.2f}"
        lines.append(
            _spaced(
                f"🧾 <b>{escape(service.name)}</b>",
                f"ID: <code>{service.id}</code>",
                f"⏱ Длительность: <b>{service.duration_min} мин</b>",
                f"💰 Цена: <b>{price_label}</b>",
                f"📌 Статус: <b>{active_label}</b>",
            )
        )
    return "\n\n────────────\n\n".join(lines)


def _format_admin_hours_list_message(rows: list[object]) -> str:
    if not rows:
        return _spaced("📅 <b>Календарь пуст.</b>", "Добавьте график командой /admin_hours_set.")

    lines: list[str] = []
    for row in rows:
        status = "Рабочий день" if row.is_working_day else "Выходной"
        lines.append(
            f"{_weekday_label(int(row.weekday))}: "
            f"<b>{row.start_time.strftime('%H:%M')} - {row.end_time.strftime('%H:%M')}</b> ({status})"
        )
    return _spaced("📅 <b>Текущий график</b>", "\n".join(lines))


async def _notify_managers(callback: CallbackQuery, text: str) -> None:
    settings = get_settings()
    manager_chat_ids = parse_manager_chat_ids(settings.telegram_manager_chat_ids)
    if not manager_chat_ids:
        return

    for chat_id in manager_chat_ids:
        try:
            await callback.bot.send_message(chat_id=chat_id, text=text)
        except Exception:
            logger.exception(
                "Failed to send manager notification",
                extra={"manager_chat_id": chat_id},
            )


async def _send_admin_error(message: Message, detail: str) -> None:
    await message.answer(
        _spaced(
            "⚠️ <b>Команда не выполнена.</b>",
            detail,
            "Подсказка: <code>/admin_help</code>",
        )
    )


async def _handle_admin_cancel_channel_command(
    message: Message,
    *,
    text: str,
    reply_text: str | None,
) -> None:
    booking_id, reason, parse_error = _parse_admin_cancel_command(
        text=text,
        reply_text=reply_text,
    )
    if parse_error or booking_id is None or reason is None:
        await _send_admin_error(message, parse_error or "Некорректная команда.")
        return

    booking, service, client, cancel_error = await _cancel_booking_by_admin(
        booking_id=booking_id,
        reason=reason,
    )
    if cancel_error or booking is None:
        await _send_admin_error(message, cancel_error or "Не удалось обработать запись.")
        return

    service_name = service.name if service is not None else "Услуга"
    client_name = "Клиент"
    if client is not None and client.full_name:
        client_name = client.full_name

    client_notify_note = "🔔 Клиент уведомлен."
    if client is None:
        client_notify_note = "⚠️ Клиент не найден, уведомление не отправлено."
    else:
        client_locale = normalize_locale(client.locale)
        try:
            await message.bot.send_message(
                chat_id=client.telegram_id,
                text=_format_client_admin_cancelled_message(
                    service_name=service_name,
                    booking_date=booking.date,
                    start_time=booking.start_time,
                    reason=reason,
                    locale=client_locale,
                ),
            )
        except Exception:
            client_notify_note = "⚠️ Не удалось отправить уведомление клиенту."
            logger.exception(
                "Failed to notify client after admin cancellation from channel",
                extra={"booking_id": str(booking.id), "channel_chat_id": message.chat.id},
            )

    await message.answer(
        _spaced(
            _format_admin_cancel_result_message(
                booking_id=booking.id,
                service_name=service_name,
                booking_date=booking.date,
                start_time=booking.start_time,
                client_name=client_name,
                reason=reason,
            ),
            client_notify_note,
        )
    )


async def _handle_admin_status_channel_command(
    message: Message,
    *,
    text: str,
    reply_text: str | None,
    command_name: str,
    target_status: BookingStatus,
) -> None:
    booking_id, parse_error = _parse_admin_status_command(
        text=text,
        reply_text=reply_text,
        command=command_name,
    )
    if parse_error or booking_id is None:
        await _send_admin_error(message, parse_error or "Некорректная команда.")
        return

    settings = get_settings()
    session_factory = get_session_factory()
    async with session_factory() as session:
        booking, service, client, status_error = await update_booking_status_by_admin(
            session=session,
            booking_id=booking_id,
            target_status=target_status,
            timezone_name=settings.timezone,
        )

    if status_error or booking is None:
        await _send_admin_error(message, status_error or "Не удалось обновить статус записи.")
        return

    service_name = service.name if service is not None else "Услуга"
    client_name = "Клиент"
    if client is not None and client.full_name:
        client_name = client.full_name

    client_notify_note = "🔔 Клиент уведомлен."
    if client is None:
        client_notify_note = "⚠️ Клиент не найден, уведомление не отправлено."
    else:
        client_locale = normalize_locale(client.locale)
        try:
            await message.bot.send_message(
                chat_id=client.telegram_id,
                text=_format_client_status_message(
                    service_name=service_name,
                    booking_date=booking.date,
                    start_time=booking.start_time,
                    status=booking.status,
                    locale=client_locale,
                ),
            )
        except Exception:
            client_notify_note = "⚠️ Не удалось отправить уведомление клиенту."
            logger.exception(
                "Failed to notify client after admin status update from channel",
                extra={
                    "booking_id": str(booking.id),
                    "target_status": booking.status.value,
                    "channel_chat_id": message.chat.id,
                },
            )

    await message.answer(
        _spaced(
            _format_admin_status_result_message(
                booking_id=booking.id,
                service_name=service_name,
                booking_date=booking.date,
                start_time=booking.start_time,
                client_name=client_name,
                status=booking.status,
            ),
            client_notify_note,
        )
    )


async def _handle_admin_services_channel_command(message: Message, *, text: str) -> None:
    if _is_command(text, "admin_services"):
        session_factory = get_session_factory()
        async with session_factory() as session:
            services = await list_services_for_admin(session, include_inactive=True)
        await message.answer(_format_admin_services_list_message(services))
        return

    if _is_command(text, "admin_service_add"):
        name, duration_min, price, parse_error = _parse_service_add_command(text)
        if parse_error or name is None or duration_min is None:
            await _send_admin_error(message, parse_error or "Некорректная команда.")
            return

        session_factory = get_session_factory()
        async with session_factory() as session:
            service = await create_service_by_admin(
                session=session,
                name=name,
                duration_min=duration_min,
                price=price,
            )
        price_label = "-" if service.price is None else f"{service.price:.2f}"
        await message.answer(
            _spaced(
                "✅ <b>Услуга добавлена</b>",
                f"🧾 Название: <b>{escape(service.name)}</b>",
                f"ID: <code>{service.id}</code>",
                f"⏱ Длительность: <b>{service.duration_min} мин</b>",
                f"💰 Цена: <b>{price_label}</b>",
            )
        )
        return

    if _is_command(text, "admin_service_edit"):
        service_id, name, duration_min, price, is_active, parse_error = _parse_service_edit_command(text)
        if parse_error or service_id is None or name is None or duration_min is None or is_active is None:
            await _send_admin_error(message, parse_error or "Некорректная команда.")
            return

        session_factory = get_session_factory()
        async with session_factory() as session:
            service = await update_service_by_admin(
                session=session,
                service_id=service_id,
                name=name,
                duration_min=duration_min,
                price=price,
                is_active=is_active,
            )
        if service is None:
            await _send_admin_error(message, "Услуга не найдена.")
            return
        price_label = "-" if service.price is None else f"{service.price:.2f}"
        await message.answer(
            _spaced(
                "✅ <b>Услуга обновлена</b>",
                f"🧾 Название: <b>{escape(service.name)}</b>",
                f"ID: <code>{service.id}</code>",
                f"⏱ Длительность: <b>{service.duration_min} мин</b>",
                f"💰 Цена: <b>{price_label}</b>",
                f"📌 Статус: <b>{'Активна' if service.is_active else 'Неактивна'}</b>",
            )
        )
        return

    if _is_command(text, "admin_service_delete"):
        service_id, parse_error = _parse_service_delete_command(text)
        if parse_error or service_id is None:
            await _send_admin_error(message, parse_error or "Некорректная команда.")
            return

        session_factory = get_session_factory()
        async with session_factory() as session:
            service = await deactivate_service_by_admin(session, service_id=service_id)
        if service is None:
            await _send_admin_error(message, "Услуга не найдена.")
            return

        await message.answer(
            _spaced(
                "✅ <b>Услуга отключена</b>",
                f"🧾 <b>{escape(service.name)}</b>",
                f"ID: <code>{service.id}</code>",
                "Услуга скрыта из каталога.",
            )
        )
        return

    await _send_admin_error(message, "Неизвестная команда управления услугами.")


async def _handle_admin_hours_channel_command(message: Message, *, text: str) -> None:
    if _is_command(text, "admin_hours"):
        session_factory = get_session_factory()
        async with session_factory() as session:
            rows = await list_working_hours_for_admin(session)
        await message.answer(_format_admin_hours_list_message(rows))
        return

    if _is_command(text, "admin_hours_set"):
        weekday, start_value, end_value, parse_error = _parse_admin_hours_set_command(text)
        if parse_error or weekday is None or start_value is None or end_value is None:
            await _send_admin_error(message, parse_error or "Некорректная команда.")
            return

        session_factory = get_session_factory()
        async with session_factory() as session:
            row = await set_working_hours_for_admin(
                session=session,
                weekday=weekday,
                start_time=start_value,
                end_time=end_value,
            )
        await message.answer(
            _spaced(
                "✅ <b>График обновлён</b>",
                f"📅 День: <b>{_weekday_label(row.weekday)}</b>",
                f"🕒 Время: <b>{row.start_time.strftime('%H:%M')} - {row.end_time.strftime('%H:%M')}</b>",
                "Статус: <b>Рабочий день</b>",
            )
        )
        return

    if _is_command(text, "admin_hours_off"):
        weekday, parse_error = _parse_admin_hours_day_command(text, "admin_hours_off")
        if parse_error or weekday is None:
            await _send_admin_error(message, parse_error or "Некорректная команда.")
            return

        session_factory = get_session_factory()
        async with session_factory() as session:
            row = await set_working_day_off_by_admin(session, weekday=weekday)
        await message.answer(
            _spaced(
                "✅ <b>День отмечен как выходной</b>",
                f"📅 День: <b>{_weekday_label(row.weekday)}</b>",
                f"🕒 Базовое время: <b>{row.start_time.strftime('%H:%M')} - {row.end_time.strftime('%H:%M')}</b>",
            )
        )
        return

    if _is_command(text, "admin_hours_delete"):
        weekday, parse_error = _parse_admin_hours_day_command(text, "admin_hours_delete")
        if parse_error or weekday is None:
            await _send_admin_error(message, parse_error or "Некорректная команда.")
            return

        session_factory = get_session_factory()
        async with session_factory() as session:
            deleted = await delete_working_hours_by_admin(session, weekday=weekday)
        if not deleted:
            await _send_admin_error(message, "Запись графика для этого дня не найдена.")
            return

        await message.answer(
            _spaced(
                "✅ <b>Запись календаря удалена</b>",
                f"📅 День: <b>{_weekday_label(weekday)}</b>",
                "Этот день будет считаться нерабочим, пока не добавите новый интервал.",
            )
        )
        return

    await _send_admin_error(message, "Неизвестная команда управления календарём.")


@router.channel_post(F.text)
async def handle_manager_channel_commands(message: Message) -> None:
    if not _is_manager_chat(message.chat.id):
        return

    text = (message.text or "").strip()
    command_name = _extract_command_name(text)
    if command_name not in ADMIN_CHANNEL_COMMANDS:
        return

    try:
        if command_name == "admin_help":
            await message.answer(_admin_help_text())
            return

        reply_text = _extract_reply_text(message.reply_to_message)
        if command_name == "admin_cancel":
            await _handle_admin_cancel_channel_command(
                message,
                text=text,
                reply_text=reply_text,
            )
            return

        status_by_command = {
            "admin_confirm": BookingStatus.CONFIRMED,
            "admin_done": BookingStatus.DONE,
            "admin_noshow": BookingStatus.NO_SHOW,
        }
        target_status = status_by_command.get(command_name)
        if target_status is not None:
            await _handle_admin_status_channel_command(
                message,
                text=text,
                reply_text=reply_text,
                command_name=command_name,
                target_status=target_status,
            )
            return

        if command_name.startswith("admin_service"):
            await _handle_admin_services_channel_command(message, text=text)
            return

        if command_name.startswith("admin_hours"):
            await _handle_admin_hours_channel_command(message, text=text)
            return

        await _send_admin_error(message, "Неизвестная админ-команда.")
    finally:
        await _safe_delete_channel_command(message)


@router.message(CommandStart())
async def handle_start(message: Message, state: FSMContext) -> None:
    locale = await _resolve_locale(state, message.from_user.id if message.from_user else None)

    await state.set_state(BookingStates.idle)
    await state.update_data(
        locale=locale,
        selected_service_id=None,
        selected_service_name=None,
        selected_date=None,
        selected_slot=None,
        quick_booking=False,
        quick_client_name=None,
        quick_client_phone=None,
        reschedule_booking_id=None,
        reschedule_service_id=None,
        reschedule_service_name=None,
        reschedule_selected_date=None,
    )
    await message.answer(
        _spaced(
            _t(
                locale,
                "🌐 <b>Выберите язык</b>",
                "🌐 <b>Choose your language</b>",
            ),
            _t(
                locale,
                "Это можно изменить в любой момент кнопкой «🌐 Язык».",
                "You can change it anytime with the “🌐 Language” button.",
            ),
        ),
        reply_markup=get_language_picker_keyboard(),
    )


@router.message(F.text.in_(LANGUAGE_MENU_TEXTS))
async def handle_language_from_menu(message: Message, state: FSMContext) -> None:
    locale = await _resolve_locale(state, message.from_user.id if message.from_user else None)
    await state.set_state(BookingStates.idle)
    await message.answer(
        _spaced(
            _t(locale, "🌐 <b>Выберите язык интерфейса</b>", "🌐 <b>Choose interface language</b>"),
            _t(locale, "Изменение применится сразу.", "Changes will apply immediately."),
        ),
        reply_markup=get_language_picker_keyboard(),
    )


@router.callback_query(F.data.startswith("lang:"))
async def handle_language_pick(callback: CallbackQuery, state: FSMContext) -> None:
    if callback.data is None:
        await callback.answer()
        return
    _, raw_locale = callback.data.split(":", maxsplit=1)
    locale = normalize_locale(raw_locale)

    telegram_user = callback.from_user
    if telegram_user is not None:
        full_name = (telegram_user.full_name or telegram_user.username or "Client").strip()
        await _save_locale(telegram_user.id, full_name[:120], locale)

    await state.set_state(BookingStates.idle)
    await state.update_data(
        locale=locale,
        selected_service_id=None,
        selected_service_name=None,
        selected_date=None,
        selected_slot=None,
        quick_booking=False,
        quick_client_name=None,
        quick_client_phone=None,
        reschedule_booking_id=None,
        reschedule_service_id=None,
        reschedule_service_name=None,
        reschedule_selected_date=None,
    )

    await callback.answer(_t(locale, "Язык сохранён ✅", "Language saved ✅"))
    settings = get_settings()
    if callback.message is not None:
        await _send_visual(
            callback.message,
            sticker_id=settings.telegram_sticker_welcome,
            fallback_dice="🎯",
        )
        await callback.message.answer(
            _spaced(
                _t(
                    locale,
                    "🌿 <b>Добро пожаловать в Easy24Booking</b>",
                    "🌿 <b>Welcome to Easy24Booking</b>",
                ),
                _t(
                    locale,
                    "Я помогу выбрать услугу и удобное время за пару шагов.",
                    "I will help you choose a service and a convenient time in just a few steps.",
                ),
                _t(
                    locale,
                    "Нажмите <b>«✨ Записаться»</b>, чтобы начать.",
                    "Tap <b>“✨ Book now”</b> to get started.",
                ),
                _t(
                    locale,
                    "Если вы уже записывались ранее, можно использовать <b>«⚡ Быстрая запись»</b>.",
                    "If you booked before, you can use <b>“⚡ Quick booking”</b>.",
                ),
            ),
            reply_markup=get_main_menu(locale),
        )


@router.message(F.text.in_(BOOK_MENU_TEXTS))
async def handle_booking_start(message: Message, state: FSMContext) -> None:
    locale = await _resolve_locale(state, message.from_user.id if message.from_user else None)
    session_factory = get_session_factory()
    async with session_factory() as session:
        services = await list_active_services(session)

    if not services:
        await state.set_state(BookingStates.idle)
        await message.answer(
            _spaced(
                _t(locale, "🧾 <b>Каталог услуг пока пуст.</b>", "🧾 <b>The service catalog is empty for now.</b>"),
                _t(locale, "Попробуйте чуть позже или обратитесь к менеджеру.", "Please try again later or contact a manager."),
            )
        )
        return

    await state.set_state(BookingStates.choosing_service)
    await state.update_data(
        selected_service_id=None,
        selected_service_name=None,
        selected_date=None,
        selected_slot=None,
        quick_booking=False,
        quick_client_name=None,
        quick_client_phone=None,
        reschedule_booking_id=None,
        reschedule_service_id=None,
        reschedule_service_name=None,
        reschedule_selected_date=None,
    )
    await message.answer(
        _spaced(
            _t(locale, "✨ <b>Выберите услугу</b>", "✨ <b>Choose a service</b>"),
            _t(locale, "Нажмите на нужный вариант ниже:", "Tap the option you need below:"),
        ),
        reply_markup=build_services_keyboard(services, locale=locale),
    )


@router.message(F.text.in_(QUICK_MENU_TEXTS))
async def handle_quick_booking_start(message: Message, state: FSMContext) -> None:
    locale = await _resolve_locale(state, message.from_user.id if message.from_user else None)
    session_factory = get_session_factory()
    async with session_factory() as session:
        user, booking, service = await get_latest_client_booking_with_service(
            session,
            telegram_id=message.from_user.id,
        )
        weekdays = await get_working_weekdays(session)

    if booking is None or service is None:
        await message.answer(
            _spaced(
                _t(locale, "⚡ <b>Быстрая запись пока недоступна.</b>", "⚡ <b>Quick booking is not available yet.</b>"),
                _t(locale, "У вас ещё нет прошлых записей для шаблона.", "You don't have previous bookings to use as a template yet."),
                _t(locale, "Нажмите <b>«✨ Записаться»</b>, чтобы создать первую запись.", "Tap <b>“✨ Book now”</b> to create your first booking."),
            ),
            reply_markup=get_main_menu(locale),
        )
        return

    if not service.is_active:
        await message.answer(
            _spaced(
                _t(locale, "⚡ <b>Быстрая запись временно недоступна.</b>", "⚡ <b>Quick booking is temporarily unavailable.</b>"),
                _t(locale, "Услуга из последней записи сейчас отключена.", "The service from your latest booking is currently disabled."),
                _t(locale, "Нажмите <b>«✨ Записаться»</b> и выберите другую услугу.", "Tap <b>“✨ Book now”</b> and choose another service."),
            ),
            reply_markup=get_main_menu(locale),
        )
        return

    candidate_dates = build_candidate_dates(sorted(weekdays))
    if not candidate_dates:
        await message.answer(
            _spaced(
                _t(locale, "⚠️ Нет доступных рабочих дней для записи.", "⚠️ No working days are available for booking."),
                _t(locale, "Попробуйте чуть позже или обратитесь к менеджеру.", "Please try again later or contact a manager."),
            ),
            reply_markup=get_main_menu(locale),
        )
        return

    quick_name = (user.full_name or "").strip() if user is not None and user.full_name else ""
    quick_phone = (user.phone or "").strip() if user is not None and user.phone else ""

    await state.set_state(BookingStates.choosing_date)
    await state.update_data(
        selected_service_id=str(service.id),
        selected_service_name=service.name,
        selected_date=None,
        selected_slot=None,
        quick_booking=True,
        quick_client_name=quick_name or None,
        quick_client_phone=quick_phone or None,
        reschedule_booking_id=None,
        reschedule_service_id=None,
        reschedule_service_name=None,
        reschedule_selected_date=None,
    )

    profile_note = (
        _t(
            locale,
            "Профиль найден: после выбора слота покажем подтверждение сразу.",
            "Profile found: after selecting a slot, we'll show confirmation right away.",
        )
        if quick_name and quick_phone
        else _t(
            locale,
            "Профиль неполный: после выбора слота попросим имя и телефон.",
            "Profile is incomplete: after selecting a slot, we'll ask for your name and phone.",
        )
    )
    await message.answer(
        _spaced(
            _t(locale, "⚡ <b>Быстрая запись</b>", "⚡ <b>Quick booking</b>"),
            _t(
                locale,
                f"🧾 Услуга из последнего визита: <b>{service.name}</b>",
                f"🧾 Service from your last visit: <b>{service.name}</b>",
            ),
            profile_note,
            _t(locale, "📅 Выберите дату:", "📅 Choose a date:"),
        ),
        reply_markup=build_dates_keyboard(candidate_dates, locale=locale),
    )


@router.callback_query(BookingStates.choosing_service, F.data.startswith("service:"))
async def handle_service_choice(callback: CallbackQuery, state: FSMContext) -> None:
    locale = await _resolve_locale(state, callback.from_user.id if callback.from_user else None)
    if callback.data is None:
        await callback.answer()
        return

    service_id = _parse_service_id(callback.data)
    if service_id is None:
        await callback.answer(_t(locale, "Некорректная услуга", "Invalid service"), show_alert=True)
        return

    session_factory = get_session_factory()
    async with session_factory() as session:
        service = await get_service(session, service_id)
        weekdays = await get_working_weekdays(session)

    if service is None:
        await callback.answer(_t(locale, "Услуга недоступна", "Service unavailable"), show_alert=True)
        return

    candidate_dates = build_candidate_dates(sorted(weekdays))
    if not candidate_dates:
        await callback.answer(_t(locale, "Нет доступных рабочих дней", "No working days available"), show_alert=True)
        return

    await state.set_state(BookingStates.choosing_date)
    await state.update_data(
        selected_service_id=str(service.id),
        selected_service_name=service.name,
        selected_date=None,
        selected_slot=None,
        quick_booking=False,
        quick_client_name=None,
        quick_client_phone=None,
    )
    await _safe_edit(
        callback,
        _spaced(
            _t(locale, "🧾 <b>Услуга выбрана</b>", "🧾 <b>Service selected</b>"),
            f"• <b>{service.name}</b>",
            _t(locale, "📅 <b>Выберите дату:</b>", "📅 <b>Choose a date:</b>"),
        ),
        reply_markup=build_dates_keyboard(candidate_dates, locale=locale),
    )
    await callback.answer()


@router.callback_query(BookingStates.choosing_date, F.data.startswith("date:"))
async def handle_date_choice(callback: CallbackQuery, state: FSMContext) -> None:
    locale = await _resolve_locale(state, callback.from_user.id if callback.from_user else None)
    if callback.data is None:
        await callback.answer()
        return

    selected_date = _parse_selected_date(callback.data)
    if selected_date is None:
        await callback.answer(_t(locale, "Некорректная дата", "Invalid date"), show_alert=True)
        return

    data = await state.get_data()
    raw_service_id = data.get("selected_service_id")
    if not raw_service_id:
        await state.set_state(BookingStates.choosing_service)
        await callback.answer(_t(locale, "Нужно сначала выбрать услугу", "Please select a service first"), show_alert=True)
        return

    try:
        service_id = UUID(str(raw_service_id))
    except ValueError:
        await state.set_state(BookingStates.choosing_service)
        await callback.answer(_t(locale, "Нужно заново выбрать услугу", "Please choose the service again"), show_alert=True)
        return

    settings = get_settings()
    session_factory = get_session_factory()
    async with session_factory() as session:
        service = await get_service(session, service_id)
        if service is None:
            await state.set_state(BookingStates.choosing_service)
            await callback.answer(_t(locale, "Услуга недоступна", "Service unavailable"), show_alert=True)
            return

        slots = await get_slots_for_service_date(
            session=session,
            service=service,
            target_date=selected_date,
            settings=settings,
        )

    if not slots:
        await state.update_data(
            selected_date=selected_date.isoformat(),
            selected_slot=None,
        )
        await _safe_edit(
            callback,
            _spaced(
                _t(locale, f"🧾 Услуга: <b>{service.name}</b>", f"🧾 Service: <b>{service.name}</b>"),
                _t(locale, f"📅 Дата: <b>{selected_date.strftime('%d.%m.%Y')}</b>", f"📅 Date: <b>{selected_date.strftime('%d.%m.%Y')}</b>"),
                _t(locale, "😔 На эту дату свободных слотов нет.", "😔 No available slots on this date."),
                _t(locale, "Можно выбрать другую дату или встать в лист ожидания.", "You can pick another date or join the waitlist."),
            ),
            reply_markup=build_waitlist_offer_keyboard(locale=locale),
        )
        await callback.answer()
        return

    await state.set_state(BookingStates.choosing_slot)
    await state.update_data(
        selected_date=selected_date.isoformat(),
        selected_slot=None,
    )
    await _safe_edit(
        callback,
        _spaced(
            _t(locale, f"🧾 Услуга: <b>{service.name}</b>", f"🧾 Service: <b>{service.name}</b>"),
            _t(locale, f"📅 Дата: <b>{selected_date.strftime('%d.%m.%Y')}</b>", f"📅 Date: <b>{selected_date.strftime('%d.%m.%Y')}</b>"),
            _t(locale, "🕒 <b>Выберите время:</b>", "🕒 <b>Choose time:</b>"),
        ),
        reply_markup=build_slots_keyboard(slots, locale=locale),
    )
    await callback.answer()


@router.callback_query(BookingStates.choosing_slot, F.data.startswith("slot:"))
async def handle_slot_choice(callback: CallbackQuery, state: FSMContext) -> None:
    locale = await _resolve_locale(state, callback.from_user.id if callback.from_user else None)
    if callback.data is None:
        await callback.answer()
        return

    parts = callback.data.split(":", maxsplit=1)
    if len(parts) != 2 or not parts[1]:
        await callback.answer(_t(locale, "Некорректный слот", "Invalid slot"), show_alert=True)
        return

    slot_value = parts[1]
    data = await state.get_data()
    selected_service_name = str(data.get("selected_service_name") or "-")
    raw_selected_date = str(data.get("selected_date") or "")
    selected_date_label = raw_selected_date
    try:
        selected_date_label = date.fromisoformat(raw_selected_date).strftime("%d.%m.%Y")
    except ValueError:
        pass

    quick_booking = bool(data.get("quick_booking"))
    quick_name_raw = str(data.get("quick_client_name") or "").strip()
    quick_phone_raw = str(data.get("quick_client_phone") or "").strip()
    quick_name = validate_full_name(quick_name_raw) if quick_name_raw else None
    quick_phone = normalize_phone_ru(quick_phone_raw) if quick_phone_raw else None

    await state.update_data(selected_slot=slot_value)
    if quick_booking and quick_name and quick_phone:
        await state.update_data(client_name=quick_name, client_phone=quick_phone)
        await state.set_state(BookingStates.confirming)
        await callback.answer(_t(locale, "Слот выбран ✅", "Slot selected ✅"))
        if callback.message is not None:
            await callback.message.answer(
                _format_booking_preview_message(
                    service_name=selected_service_name,
                    selected_date_label=selected_date_label,
                    selected_slot=slot_value,
                    client_name=quick_name,
                    client_phone=quick_phone,
                    locale=locale,
                    quick_mode=True,
                ),
                reply_markup=build_confirmation_keyboard(locale=locale),
            )
        return

    if quick_booking and quick_name and not quick_phone:
        await state.update_data(client_name=quick_name)
        await state.set_state(BookingStates.input_phone)
        await callback.answer(_t(locale, "Слот выбран ✅", "Slot selected ✅"))
        if callback.message is not None:
            await callback.message.answer(
                _spaced(
                    _t(locale, f"🕒 Вы выбрали время <b>{slot_value}</b>", f"🕒 You selected time <b>{slot_value}</b>"),
                    _t(locale, f"👤 Имя из профиля: <b>{quick_name}</b>", f"👤 Name from profile: <b>{quick_name}</b>"),
                    _t(locale, "📱 Введите телефон в формате +7XXXXXXXXXX.", "📱 Enter your phone in format +7XXXXXXXXXX."),
                )
            )
        return

    await state.set_state(BookingStates.input_name)
    await callback.answer(_t(locale, "Слот выбран ✅", "Slot selected ✅"))
    if callback.message is not None:
        await callback.message.answer(
            _spaced(
                _t(locale, f"🕒 Вы выбрали время <b>{slot_value}</b>", f"🕒 You selected time <b>{slot_value}</b>"),
                _t(locale, "👤 Введите ваше имя (2-60 символов).", "👤 Enter your name (2-60 characters)."),
            )
        )


@router.callback_query(BookingStates.choosing_date, F.data == "waitlist:join")
async def handle_waitlist_join(callback: CallbackQuery, state: FSMContext) -> None:
    locale = await _resolve_locale(state, callback.from_user.id if callback.from_user else None)
    telegram_user = callback.from_user
    if telegram_user is None:
        await callback.answer(_t(locale, "Не удалось определить пользователя", "Could not identify user"), show_alert=True)
        return

    data = await state.get_data()
    raw_service_id = data.get("selected_service_id")
    raw_selected_date = data.get("selected_date")
    if not raw_service_id or not raw_selected_date:
        await callback.answer(_t(locale, "Сначала выберите услугу и дату", "Select a service and date first"), show_alert=True)
        return

    try:
        service_id = UUID(str(raw_service_id))
        wait_date = date.fromisoformat(str(raw_selected_date))
    except ValueError:
        await callback.answer(_t(locale, "Некорректные данные услуги или даты", "Invalid service or date data"), show_alert=True)
        return

    full_name = (telegram_user.full_name or telegram_user.username or "Client").strip()
    full_name = full_name[:120] if full_name else "Client"

    service_name = _t(locale, "Услуга", "Service")
    client_name = full_name
    client_phone = "-"

    session_factory = get_session_factory()
    async with session_factory() as session:
        service = await get_service(session, service_id)
        if service is None:
            await callback.answer(_t(locale, "Услуга недоступна", "Service unavailable"), show_alert=True)
            return
        service_name = service.name

        waitlist_entry, created, waitlist_error = await add_client_to_waitlist(
            session=session,
            telegram_id=telegram_user.id,
            full_name=full_name,
            service_id=service_id,
            wait_date=wait_date,
            locale=locale,
        )
        if waitlist_error:
            await callback.answer(_translate_error_text(locale, waitlist_error), show_alert=True)
            return

        if waitlist_entry is not None:
            client = await session.get(User, waitlist_entry.client_id)
            if client is not None:
                if client.full_name:
                    client_name = client.full_name
                if client.phone:
                    client_phone = client.phone

    await state.set_state(BookingStates.idle)
    await state.update_data(
        selected_service_id=None,
        selected_service_name=None,
        selected_date=None,
        selected_slot=None,
        quick_booking=False,
        quick_client_name=None,
        quick_client_phone=None,
        reschedule_booking_id=None,
        reschedule_service_id=None,
        reschedule_service_name=None,
        reschedule_selected_date=None,
    )

    if not created:
        await callback.answer(_t(locale, "Вы уже в листе ожидания", "You are already in the waitlist"), show_alert=True)
        if callback.message is not None:
            await callback.message.answer(
                _spaced(
                    _t(locale, "ℹ️ <b>Вы уже в листе ожидания на эту дату.</b>", "ℹ️ <b>You are already in the waitlist for this date.</b>"),
                    _t(locale, "Если нужно, создайте новую запись на другую дату.", "If needed, create a new booking for another date."),
                ),
                reply_markup=get_main_menu(locale),
            )
        return

    await callback.answer(_t(locale, "Добавлено в лист ожидания ✅", "Added to waitlist ✅"))
    if callback.message is not None:
        await callback.message.answer(
            _spaced(
                _t(locale, "🔔 <b>Готово, вы в листе ожидания.</b>", "🔔 <b>Done, you are in the waitlist.</b>"),
                _t(locale, f"🧾 Услуга: <b>{service_name}</b>", f"🧾 Service: <b>{service_name}</b>"),
                _t(locale, f"📅 Дата: <b>{wait_date.strftime('%d.%m.%Y')}</b>", f"📅 Date: <b>{wait_date.strftime('%d.%m.%Y')}</b>"),
                _t(locale, "Если освободится время, менеджер свяжется с вами.", "If a slot opens up, a manager will contact you."),
            ),
            reply_markup=get_main_menu(locale),
        )

    if waitlist_entry is not None:
        await _notify_managers(
            callback,
            _format_waitlist_manager_message(
                waitlist_entry=waitlist_entry,
                service_name=service_name,
                wait_date=wait_date,
                client_name=client_name,
                client_phone=client_phone,
                telegram_id=telegram_user.id,
            ),
        )


@router.message(BookingStates.input_name, F.text)
async def handle_input_name(message: Message, state: FSMContext) -> None:
    locale = await _resolve_locale(state, message.from_user.id if message.from_user else None)
    normalized = validate_full_name(message.text or "")
    if normalized is None:
        await message.answer(
            _spaced(
                _t(locale, "👤 Имя должно быть длиной от 2 до 60 символов.", "👤 Name must be 2 to 60 characters long."),
                _t(locale, "Попробуйте ещё раз.", "Please try again."),
            )
        )
        return

    await state.update_data(client_name=normalized)
    await state.set_state(BookingStates.input_phone)
    await message.answer(
        _t(
            locale,
            "📱 Отлично! Теперь введите телефон в формате +7XXXXXXXXXX.",
            "📱 Great! Now enter your phone number in format +7XXXXXXXXXX.",
        )
    )


@router.message(BookingStates.input_phone, F.text)
async def handle_input_phone(message: Message, state: FSMContext) -> None:
    locale = await _resolve_locale(state, message.from_user.id if message.from_user else None)
    normalized = normalize_phone_ru(message.text or "")
    if normalized is None:
        await message.answer(
            _spaced(
                _t(locale, "📱 Некорректный номер.", "📱 Invalid phone number."),
                _t(locale, "Пример: +79991234567 или 89991234567.", "Example: +79991234567 or 89991234567."),
            )
        )
        return

    await state.update_data(client_phone=normalized)
    await state.set_state(BookingStates.confirming)

    data = await state.get_data()
    service_name = str(data.get("selected_service_name") or "-")
    raw_selected_date = str(data.get("selected_date") or "-")
    selected_date_label = raw_selected_date
    try:
        selected_date_label = date.fromisoformat(raw_selected_date).strftime("%d.%m.%Y")
    except ValueError:
        pass
    selected_slot = str(data.get("selected_slot") or "-")
    client_name = str(data.get("client_name") or "-")

    await message.answer(
        _format_booking_preview_message(
            service_name=service_name,
            selected_date_label=selected_date_label,
            selected_slot=selected_slot,
            client_name=client_name,
            client_phone=normalized,
            locale=locale,
        ),
        reply_markup=build_confirmation_keyboard(locale=locale),
    )


@router.callback_query(
    BookingStates.choosing_date,
    F.data == "back:services",
)
@router.callback_query(
    BookingStates.choosing_slot,
    F.data == "back:services",
)
async def handle_back_to_services(callback: CallbackQuery, state: FSMContext) -> None:
    locale = await _resolve_locale(state, callback.from_user.id if callback.from_user else None)
    session_factory = get_session_factory()
    async with session_factory() as session:
        services = await list_active_services(session)

    if not services:
        await state.set_state(BookingStates.idle)
        await callback.answer(_t(locale, "Список услуг пуст", "Service list is empty"), show_alert=True)
        return

    await state.set_state(BookingStates.choosing_service)
    await state.update_data(
        selected_service_id=None,
        selected_service_name=None,
        selected_date=None,
        selected_slot=None,
        quick_booking=False,
        quick_client_name=None,
        quick_client_phone=None,
        reschedule_booking_id=None,
        reschedule_service_id=None,
        reschedule_service_name=None,
        reschedule_selected_date=None,
    )
    await _safe_edit(
        callback,
        _spaced(
            _t(locale, "✨ <b>Выберите услугу</b>", "✨ <b>Choose a service</b>"),
            _t(locale, "Нажмите на нужный вариант ниже:", "Tap the option you need below:"),
        ),
        reply_markup=build_services_keyboard(services, locale=locale),
    )
    await callback.answer()


@router.callback_query(BookingStates.confirming, F.data == "back:slots")
async def handle_back_to_slots_from_confirmation(callback: CallbackQuery, state: FSMContext) -> None:
    locale = await _resolve_locale(state, callback.from_user.id if callback.from_user else None)
    data = await state.get_data()
    raw_service_id = data.get("selected_service_id")
    raw_selected_date = data.get("selected_date")

    if not raw_service_id or not raw_selected_date:
        await state.set_state(BookingStates.choosing_service)
        await callback.answer(
            _t(locale, "Нужно заново выбрать услугу и дату", "Please choose service and date again"),
            show_alert=True,
        )
        return

    try:
        service_id = UUID(str(raw_service_id))
        selected_date = date.fromisoformat(str(raw_selected_date))
    except ValueError:
        await state.set_state(BookingStates.choosing_service)
        await callback.answer(_t(locale, "Некорректные данные выбора", "Invalid selected data"), show_alert=True)
        return

    settings = get_settings()
    session_factory = get_session_factory()
    async with session_factory() as session:
        service = await get_service(session, service_id)
        if service is None:
            await state.set_state(BookingStates.choosing_service)
            await callback.answer(_t(locale, "Услуга недоступна", "Service unavailable"), show_alert=True)
            return

        slots = await get_slots_for_service_date(
            session=session,
            service=service,
            target_date=selected_date,
            settings=settings,
        )

    if not slots:
        await callback.answer(
            _t(locale, "Свободных слотов на эту дату больше нет", "No slots left for this date"),
            show_alert=True,
        )
        return

    await state.set_state(BookingStates.choosing_slot)
    await state.update_data(selected_slot=None)
    await _safe_edit(
        callback,
        _spaced(
            _t(locale, f"🧾 Услуга: <b>{service.name}</b>", f"🧾 Service: <b>{service.name}</b>"),
            _t(locale, f"📅 Дата: <b>{selected_date.strftime('%d.%m.%Y')}</b>", f"📅 Date: <b>{selected_date.strftime('%d.%m.%Y')}</b>"),
            _t(locale, "🕒 <b>Выберите время:</b>", "🕒 <b>Choose time:</b>"),
        ),
        reply_markup=build_slots_keyboard(slots, locale=locale),
    )
    await callback.answer()


@router.callback_query(BookingStates.choosing_slot, F.data == "back:dates")
async def handle_back_to_dates(callback: CallbackQuery, state: FSMContext) -> None:
    locale = await _resolve_locale(state, callback.from_user.id if callback.from_user else None)
    data = await state.get_data()
    service_name = str(data.get("selected_service_name") or _t(locale, "услуга", "service"))

    session_factory = get_session_factory()
    async with session_factory() as session:
        weekdays = await get_working_weekdays(session)

    candidate_dates = build_candidate_dates(sorted(weekdays))
    if not candidate_dates:
        await callback.answer(_t(locale, "Нет доступных рабочих дней", "No working days available"), show_alert=True)
        return

    await state.set_state(BookingStates.choosing_date)
    await state.update_data(selected_date=None, selected_slot=None)
    await _safe_edit(
        callback,
        _spaced(
            _t(locale, "🧾 <b>Услуга выбрана</b>", "🧾 <b>Service selected</b>"),
            f"• <b>{service_name}</b>",
            _t(locale, "📅 <b>Выберите дату:</b>", "📅 <b>Choose a date:</b>"),
        ),
        reply_markup=build_dates_keyboard(candidate_dates, locale=locale),
    )
    await callback.answer()


@router.callback_query(BookingStates.confirming, F.data == "confirm:booking")
async def handle_confirm_booking(callback: CallbackQuery, state: FSMContext) -> None:
    locale = await _resolve_locale(state, callback.from_user.id if callback.from_user else None)
    telegram_user = callback.from_user
    if telegram_user is None:
        await callback.answer(_t(locale, "Не удалось определить пользователя", "Could not identify user"), show_alert=True)
        return

    data = await state.get_data()
    raw_service_id = data.get("selected_service_id")
    raw_selected_date = data.get("selected_date")
    raw_selected_slot = data.get("selected_slot")
    client_name = data.get("client_name")
    client_phone = data.get("client_phone")

    if not all([raw_service_id, raw_selected_date, raw_selected_slot, client_name, client_phone]):
        await callback.answer(
            _t(locale, "Данные неполные, начните запись заново", "Incomplete data, start booking again"),
            show_alert=True,
        )
        await state.set_state(BookingStates.idle)
        return

    try:
        service_id = UUID(str(raw_service_id))
        booking_date = date.fromisoformat(str(raw_selected_date))
    except ValueError:
        await callback.answer(_t(locale, "Некорректные данные услуги/даты", "Invalid service/date data"), show_alert=True)
        await state.set_state(BookingStates.idle)
        return

    start_time = _parse_slot_time(str(raw_selected_slot))
    if start_time is None:
        await callback.answer(_t(locale, "Некорректный формат времени", "Invalid time format"), show_alert=True)
        await state.set_state(BookingStates.idle)
        return

    settings = get_settings()
    session_factory = get_session_factory()
    async with session_factory() as session:
        service = await get_service(session, service_id)
        if service is None:
            await callback.answer(_t(locale, "Услуга недоступна", "Service unavailable"), show_alert=True)
            await state.set_state(BookingStates.idle)
            return

        try:
            booking = await create_booking_for_client(
                session=session,
                settings=settings,
                telegram_id=telegram_user.id,
                full_name=str(client_name),
                phone=str(client_phone),
                service=service,
                booking_date=booking_date,
                start_time=start_time,
                locale=locale,
            )
        except ValueError as exc:
            await callback.answer(_translate_error_text(locale, str(exc)), show_alert=True)
            return
        except IntegrityError:
            await session.rollback()
            await callback.answer(
                _t(locale, "Этот слот уже заняли. Выберите другое время.", "This slot has been taken. Please choose another time."),
                show_alert=True,
            )
            return

    await state.set_state(BookingStates.done)
    await state.update_data(booking_id=str(booking.id))
    await callback.answer(_t(locale, "Запись создана ✅", "Booking created ✅"))
    if callback.message is not None:
        await _send_visual(
            callback.message,
            sticker_id=settings.telegram_sticker_booked,
            fallback_dice="🎲",
        )
        await callback.message.answer(
            _spaced(
                _t(locale, "🎉 <b>Запись успешно оформлена!</b>", "🎉 <b>Your booking is confirmed!</b>"),
                _t(locale, f"🧾 Услуга: <b>{service.name}</b>", f"🧾 Service: <b>{service.name}</b>"),
                _t(locale, f"📅 Дата: <b>{booking_date.strftime('%d.%m.%Y')}</b>", f"📅 Date: <b>{booking_date.strftime('%d.%m.%Y')}</b>"),
                _t(locale, f"🕒 Время: <b>{start_time.strftime('%H:%M')}</b>", f"🕒 Time: <b>{start_time.strftime('%H:%M')}</b>"),
                _t(locale, "Мы напомним о визите заранее.", "We will remind you in advance."),
            ),
            reply_markup=get_main_menu(locale),
        )
    await _notify_managers(
        callback,
        _format_new_booking_manager_message(
            booking_id=booking.id,
            service_name=service.name,
            booking_date=booking_date,
            start_time=start_time,
            client_name=str(client_name),
            client_phone=str(client_phone),
            telegram_id=telegram_user.id,
        ),
    )
    await state.set_state(BookingStates.idle)


@router.callback_query(F.data == "flow:cancel")
async def handle_flow_cancel_callback(callback: CallbackQuery, state: FSMContext) -> None:
    locale = await _resolve_locale(state, callback.from_user.id if callback.from_user else None)
    await state.set_state(BookingStates.idle)
    await state.update_data(
        locale=locale,
        selected_service_id=None,
        selected_service_name=None,
        selected_date=None,
        selected_slot=None,
        quick_booking=False,
        quick_client_name=None,
        quick_client_phone=None,
        reschedule_booking_id=None,
        reschedule_service_id=None,
        reschedule_service_name=None,
        reschedule_selected_date=None,
    )
    await callback.answer(_t(locale, "Действие отменено", "Action cancelled"))
    if callback.message is not None:
        await callback.message.answer(
            _spaced(
                "🛑",
                _t(locale, "Текущее действие отменено.", "Current action was cancelled."),
            ),
            reply_markup=get_main_menu(locale),
        )


@router.message(F.text.in_(MY_BOOKINGS_MENU_TEXTS))
async def handle_my_bookings(message: Message) -> None:
    locale = await _resolve_locale(None, message.from_user.id if message.from_user else None)
    session_factory = get_session_factory()
    async with session_factory() as session:
        bookings = await list_client_bookings(session, telegram_id=message.from_user.id)

    if not bookings:
        await message.answer(
            _spaced(
                _t(locale, "📭 У вас пока нет записей.", "📭 You have no bookings yet."),
                _t(locale, "Нажмите <b>«✨ Записаться»</b>, чтобы создать первую.", "Tap <b>“✨ Book now”</b> to create your first one."),
            )
        )
        return

    for booking, service in bookings:
        status_label = _status_label(booking.status, locale)
        text = _spaced(
            _t(locale, f"🧾 <b>{service.name}</b>", f"🧾 <b>{service.name}</b>"),
            _t(locale, f"📅 Дата: <b>{booking.date.strftime('%d.%m.%Y')}</b>", f"📅 Date: <b>{booking.date.strftime('%d.%m.%Y')}</b>"),
            _t(locale, f"🕒 Время: <b>{booking.start_time.strftime('%H:%M')}</b>", f"🕒 Time: <b>{booking.start_time.strftime('%H:%M')}</b>"),
            _t(locale, f"📌 Статус: <b>{status_label}</b>", f"📌 Status: <b>{status_label}</b>"),
        )

        if booking.status in {BookingStatus.NEW, BookingStatus.CONFIRMED}:
            await message.answer(
                text,
                reply_markup=build_booking_actions_keyboard(booking.id, locale=locale),
            )
        else:
            await message.answer(text)


@router.callback_query(F.data.startswith("reschedule_booking:"))
async def handle_reschedule_booking_start(callback: CallbackQuery, state: FSMContext) -> None:
    locale = await _resolve_locale(state, callback.from_user.id if callback.from_user else None)
    if callback.data is None:
        await callback.answer()
        return

    booking_id = _parse_booking_id(callback.data, "reschedule_booking:")
    if booking_id is None:
        await callback.answer(_t(locale, "Некорректные данные записи", "Invalid booking data"), show_alert=True)
        return

    session_factory = get_session_factory()
    async with session_factory() as session:
        booking, service = await get_client_booking_with_service(
            session,
            booking_id=booking_id,
            telegram_id=callback.from_user.id,
        )
        weekdays = await get_working_weekdays(session)

    if booking is None:
        await callback.answer(_t(locale, "Запись не найдена", "Booking not found"), show_alert=True)
        return
    if service is None or not service.is_active:
        await callback.answer(_t(locale, "Услуга недоступна для переноса", "Service unavailable for rescheduling"), show_alert=True)
        return
    if booking.status not in {BookingStatus.NEW, BookingStatus.CONFIRMED}:
        await callback.answer(_t(locale, "Эту запись уже нельзя перенести", "This booking can no longer be rescheduled"), show_alert=True)
        return

    candidate_dates = build_candidate_dates(sorted(weekdays))
    if not candidate_dates:
        await callback.answer(_t(locale, "Нет доступных рабочих дней", "No working days available"), show_alert=True)
        return

    await state.set_state(BookingStates.reschedule_choosing_date)
    await state.update_data(
        reschedule_booking_id=str(booking.id),
        reschedule_service_id=str(service.id),
        reschedule_service_name=service.name,
        reschedule_selected_date=None,
    )
    await _safe_edit(
        callback,
        _spaced(
            _t(locale, "🔁 <b>Перенос записи</b>", "🔁 <b>Reschedule booking</b>"),
            _t(locale, f"🧾 Услуга: <b>{service.name}</b>", f"🧾 Service: <b>{service.name}</b>"),
            _t(
                locale,
                f"📆 Текущее время: <b>{booking.date.strftime('%d.%m.%Y')} {booking.start_time.strftime('%H:%M')}</b>",
                f"📆 Current time: <b>{booking.date.strftime('%d.%m.%Y')} {booking.start_time.strftime('%H:%M')}</b>",
            ),
            _t(locale, "📅 Выберите новую дату:", "📅 Choose a new date:"),
        ),
        reply_markup=build_reschedule_dates_keyboard(candidate_dates, locale=locale),
    )
    await callback.answer()


@router.callback_query(BookingStates.reschedule_choosing_date, F.data == "reschedule_back:list")
async def handle_reschedule_back_to_list(callback: CallbackQuery, state: FSMContext) -> None:
    locale = await _resolve_locale(state, callback.from_user.id if callback.from_user else None)
    await state.set_state(BookingStates.idle)
    await state.update_data(
        reschedule_booking_id=None,
        reschedule_service_id=None,
        reschedule_service_name=None,
        reschedule_selected_date=None,
    )
    await _safe_edit(
        callback,
        _spaced(
            _t(locale, "↩️ Возврат к списку записей.", "↩️ Back to booking list."),
            _t(locale, "Нажмите <b>«📋 Мои записи»</b> в меню.", "Tap <b>“📋 My bookings”</b> in the menu."),
        ),
        reply_markup=None,
    )
    await callback.answer()


@router.callback_query(BookingStates.reschedule_choosing_date, F.data.startswith("reschedule_date:"))
async def handle_reschedule_date_choice(callback: CallbackQuery, state: FSMContext) -> None:
    locale = await _resolve_locale(state, callback.from_user.id if callback.from_user else None)
    if callback.data is None:
        await callback.answer()
        return

    selected_date = _parse_date_with_prefix(callback.data, "reschedule_date:")
    if selected_date is None:
        await callback.answer(_t(locale, "Некорректная дата", "Invalid date"), show_alert=True)
        return

    data = await state.get_data()
    raw_service_id = data.get("reschedule_service_id")
    service_name = str(data.get("reschedule_service_name") or _t(locale, "услуга", "service"))
    if not raw_service_id:
        await callback.answer(_t(locale, "Нужно заново выбрать запись", "Please choose booking again"), show_alert=True)
        await state.set_state(BookingStates.idle)
        return

    try:
        service_id = UUID(str(raw_service_id))
    except ValueError:
        await callback.answer(_t(locale, "Нужно заново выбрать запись", "Please choose booking again"), show_alert=True)
        await state.set_state(BookingStates.idle)
        return

    settings = get_settings()
    session_factory = get_session_factory()
    async with session_factory() as session:
        service = await get_service(session, service_id)
        if service is None:
            await callback.answer(_t(locale, "Услуга недоступна", "Service unavailable"), show_alert=True)
            await state.set_state(BookingStates.idle)
            return

        slots = await get_slots_for_service_date(
            session=session,
            service=service,
            target_date=selected_date,
            settings=settings,
        )

    if not slots:
        await callback.answer(_t(locale, "На эту дату свободных слотов нет", "No available slots on this date"), show_alert=True)
        return

    await state.set_state(BookingStates.reschedule_choosing_slot)
    await state.update_data(reschedule_selected_date=selected_date.isoformat())
    await _safe_edit(
        callback,
        _spaced(
            _t(locale, "🔁 <b>Перенос записи</b>", "🔁 <b>Reschedule booking</b>"),
            _t(locale, f"🧾 Услуга: <b>{service_name}</b>", f"🧾 Service: <b>{service_name}</b>"),
            _t(locale, f"📅 Новая дата: <b>{selected_date.strftime('%d.%m.%Y')}</b>", f"📅 New date: <b>{selected_date.strftime('%d.%m.%Y')}</b>"),
            _t(locale, "🕒 Выберите новое время:", "🕒 Choose a new time:"),
        ),
        reply_markup=build_reschedule_slots_keyboard(slots, locale=locale),
    )
    await callback.answer()


@router.callback_query(BookingStates.reschedule_choosing_slot, F.data == "reschedule_back:dates")
async def handle_reschedule_back_to_dates(callback: CallbackQuery, state: FSMContext) -> None:
    locale = await _resolve_locale(state, callback.from_user.id if callback.from_user else None)
    data = await state.get_data()
    service_name = str(data.get("reschedule_service_name") or _t(locale, "услуга", "service"))

    session_factory = get_session_factory()
    async with session_factory() as session:
        weekdays = await get_working_weekdays(session)

    candidate_dates = build_candidate_dates(sorted(weekdays))
    if not candidate_dates:
        await callback.answer(_t(locale, "Нет доступных рабочих дней", "No working days available"), show_alert=True)
        return

    await state.set_state(BookingStates.reschedule_choosing_date)
    await state.update_data(reschedule_selected_date=None)
    await _safe_edit(
        callback,
        _spaced(
            _t(locale, "🔁 <b>Перенос записи</b>", "🔁 <b>Reschedule booking</b>"),
            _t(locale, f"🧾 Услуга: <b>{service_name}</b>", f"🧾 Service: <b>{service_name}</b>"),
            _t(locale, "📅 Выберите новую дату:", "📅 Choose a new date:"),
        ),
        reply_markup=build_reschedule_dates_keyboard(candidate_dates, locale=locale),
    )
    await callback.answer()


@router.callback_query(BookingStates.reschedule_choosing_slot, F.data.startswith("reschedule_slot:"))
async def handle_reschedule_slot_choice(callback: CallbackQuery, state: FSMContext) -> None:
    locale = await _resolve_locale(state, callback.from_user.id if callback.from_user else None)
    if callback.data is None:
        await callback.answer()
        return

    selected_slot = _parse_time_with_prefix(callback.data, "reschedule_slot:")
    if selected_slot is None:
        await callback.answer(_t(locale, "Некорректный формат времени", "Invalid time format"), show_alert=True)
        return

    data = await state.get_data()
    raw_booking_id = data.get("reschedule_booking_id")
    raw_selected_date = data.get("reschedule_selected_date")
    if not raw_booking_id or not raw_selected_date:
        await callback.answer(_t(locale, "Нужно заново выбрать запись", "Please choose booking again"), show_alert=True)
        await state.set_state(BookingStates.idle)
        return

    try:
        booking_id = UUID(str(raw_booking_id))
        selected_date = date.fromisoformat(str(raw_selected_date))
    except ValueError:
        await callback.answer(_t(locale, "Некорректные данные переноса", "Invalid reschedule data"), show_alert=True)
        await state.set_state(BookingStates.idle)
        return

    settings = get_settings()
    old_date: Optional[date] = None
    old_start_time: Optional[time] = None
    service_name = _t(locale, "Услуга", "Service")
    client_name = "-"
    client_phone = "-"

    session_factory = get_session_factory()
    async with session_factory() as session:
        before_booking, before_service = await get_client_booking_with_service(
            session,
            booking_id=booking_id,
            telegram_id=callback.from_user.id,
        )
        if before_booking is not None:
            old_date = before_booking.date
            old_start_time = before_booking.start_time
        if before_service is not None:
            service_name = before_service.name

        booking, service, error = await reschedule_booking_for_client(
            session=session,
            settings=settings,
            booking_id=booking_id,
            telegram_id=callback.from_user.id,
            new_date=selected_date,
            new_start_time=selected_slot,
        )
        if booking is not None:
            client = await session.get(User, booking.client_id)
            if client is not None:
                client_name = client.full_name or "-"
                client_phone = client.phone or "-"
        if service is not None:
            service_name = service.name

    if error is not None:
        await callback.answer(_translate_error_text(locale, error), show_alert=True)
        return
    if booking is None or old_date is None or old_start_time is None:
        await callback.answer(_t(locale, "Не удалось перенести запись", "Could not reschedule booking"), show_alert=True)
        return

    await state.set_state(BookingStates.idle)
    await state.update_data(
        locale=locale,
        reschedule_booking_id=None,
        reschedule_service_id=None,
        reschedule_service_name=None,
        reschedule_selected_date=None,
    )

    await callback.answer(_t(locale, "Запись перенесена ✅", "Booking rescheduled ✅"))
    if callback.message is not None:
        try:
            await callback.message.edit_reply_markup(reply_markup=None)
        except TelegramBadRequest:
            pass
        await _send_visual(
            callback.message,
            sticker_id=settings.telegram_sticker_booked,
            fallback_dice="🎲",
        )
        await callback.message.answer(
            _spaced(
                _t(locale, "🔁 <b>Запись успешно перенесена</b>", "🔁 <b>Booking rescheduled</b>"),
                _t(locale, f"🧾 Услуга: <b>{service_name}</b>", f"🧾 Service: <b>{service_name}</b>"),
                _t(locale, f"📅 Новая дата: <b>{booking.date.strftime('%d.%m.%Y')}</b>", f"📅 New date: <b>{booking.date.strftime('%d.%m.%Y')}</b>"),
                _t(locale, f"🕒 Новое время: <b>{booking.start_time.strftime('%H:%M')}</b>", f"🕒 New time: <b>{booking.start_time.strftime('%H:%M')}</b>"),
            ),
            reply_markup=get_main_menu(locale),
        )

    await _notify_managers(
        callback,
        _format_rescheduled_booking_manager_message(
            booking_id=booking.id,
            service_name=service_name,
            old_date=old_date,
            old_start_time=old_start_time,
            new_date=booking.date,
            new_start_time=booking.start_time,
            client_name=client_name,
            client_phone=client_phone,
            telegram_id=callback.from_user.id,
        ),
    )


@router.callback_query(F.data.startswith("reminder_confirm:"))
async def handle_reminder_confirm(callback: CallbackQuery) -> None:
    locale = await _resolve_locale(None, callback.from_user.id if callback.from_user else None)
    if callback.data is None:
        await callback.answer()
        return

    booking_id = _parse_booking_id(callback.data, "reminder_confirm:")
    if booking_id is None:
        await callback.answer(_t(locale, "Некорректные данные записи", "Invalid booking data"), show_alert=True)
        return

    service_name = _t(locale, "услуга", "service")
    booking_date: Optional[date] = None
    booking_start: Optional[time] = None

    session_factory = get_session_factory()
    async with session_factory() as session:
        booking, was_confirmed, result_text = await confirm_booking_by_reminder(
            session=session,
            booking_id=booking_id,
            telegram_id=callback.from_user.id,
        )
        if booking is not None:
            service = await session.get(Service, booking.service_id)
            if service is not None:
                service_name = service.name
            booking_date = booking.date
            booking_start = booking.start_time
            client = await session.get(User, booking.client_id)
            if client is not None:
                locale = normalize_locale(client.locale)

    if booking is None:
        await callback.answer(_translate_error_text(locale, result_text), show_alert=True)
        return

    await callback.answer(
        _t(locale, "Подтверждено ✅", "Confirmed ✅")
        if was_confirmed
        else _t(locale, "Без изменений", "No changes")
    )
    if callback.message is not None:
        try:
            await callback.message.edit_reply_markup(reply_markup=None)
        except TelegramBadRequest:
            pass
        if booking_date is not None and booking_start is not None:
            await callback.message.answer(
                _spaced(
                    (
                        _t(locale, "✅ <b>Спасибо, визит подтверждён.</b>", "✅ <b>Thank you, your visit is confirmed.</b>")
                        if was_confirmed
                        else _t(locale, "ℹ️ <b>Запись уже была подтверждена.</b>", "ℹ️ <b>This booking was already confirmed.</b>")
                    ),
                    _t(locale, f"🧾 Услуга: <b>{service_name}</b>", f"🧾 Service: <b>{service_name}</b>"),
                    _t(locale, f"📅 Дата: <b>{booking_date.strftime('%d.%m.%Y')}</b>", f"📅 Date: <b>{booking_date.strftime('%d.%m.%Y')}</b>"),
                    _t(locale, f"🕒 Время: <b>{booking_start.strftime('%H:%M')}</b>", f"🕒 Time: <b>{booking_start.strftime('%H:%M')}</b>"),
                )
            )


@router.callback_query(F.data.startswith("reminder_decline:"))
async def handle_reminder_decline(callback: CallbackQuery) -> None:
    locale = await _resolve_locale(None, callback.from_user.id if callback.from_user else None)
    if callback.data is None:
        await callback.answer()
        return

    booking_id = _parse_booking_id(callback.data, "reminder_decline:")
    if booking_id is None:
        await callback.answer(_t(locale, "Некорректные данные записи", "Invalid booking data"), show_alert=True)
        return

    service_name = "-"
    client_name = "-"
    client_phone = "-"

    session_factory = get_session_factory()
    async with session_factory() as session:
        booking, was_cancelled, result_text = await decline_booking_by_reminder(
            session=session,
            booking_id=booking_id,
            telegram_id=callback.from_user.id,
        )
        if booking is not None:
            service = await session.get(Service, booking.service_id)
            if service is not None:
                service_name = service.name
            client = await session.get(User, booking.client_id)
            if client is not None:
                client_name = client.full_name or "-"
                client_phone = client.phone or "-"
                locale = normalize_locale(client.locale)

    if booking is None:
        await callback.answer(_translate_error_text(locale, result_text), show_alert=True)
        return

    await callback.answer(
        _t(locale, "Запись отменена ✅", "Booking cancelled ✅")
        if was_cancelled
        else _t(locale, "Без изменений", "No changes")
    )
    if callback.message is not None:
        try:
            await callback.message.edit_reply_markup(reply_markup=None)
        except TelegramBadRequest:
            pass

    if was_cancelled and callback.message is not None:
        settings = get_settings()
        await _send_visual(
            callback.message,
            sticker_id=settings.telegram_sticker_cancelled,
            fallback_dice="🎳",
        )
        await callback.message.answer(
            _spaced(
                _t(locale, "❌ <b>Запись отменена по вашему подтверждению.</b>", "❌ <b>Your booking was cancelled as requested.</b>"),
                _t(locale, "Если захотите, можно выбрать новое время в пару нажатий.", "If you want, you can pick a new time in a couple of taps."),
            ),
            reply_markup=get_main_menu(locale),
        )
        await _notify_managers(
            callback,
            _format_cancelled_booking_manager_message(
                booking_id=booking.id,
                service_name=service_name,
                booking_date=booking.date,
                start_time=booking.start_time,
                client_name=client_name,
                client_phone=client_phone,
                telegram_id=callback.from_user.id,
            ),
        )
        return

    if callback.message is not None:
        await callback.message.answer(f"ℹ️ {_translate_error_text(locale, result_text)}")


@router.callback_query(F.data.startswith("cancel_booking:"))
async def handle_cancel_booking_click(callback: CallbackQuery) -> None:
    locale = await _resolve_locale(None, callback.from_user.id if callback.from_user else None)
    if callback.data is None:
        await callback.answer()
        return

    booking_id = _parse_booking_id(callback.data, "cancel_booking:")
    if booking_id is None:
        await callback.answer(_t(locale, "Некорректные данные записи", "Invalid booking data"), show_alert=True)
        return

    await callback.answer()
    if callback.message is not None:
        await callback.message.answer(
            _t(locale, "⚠️ Подтвердите отмену записи.", "⚠️ Confirm booking cancellation."),
            reply_markup=build_cancel_confirmation_keyboard(booking_id, locale=locale),
        )


@router.callback_query(F.data == "keep_booking")
async def handle_keep_booking(callback: CallbackQuery) -> None:
    locale = await _resolve_locale(None, callback.from_user.id if callback.from_user else None)
    await callback.answer(_t(locale, "Оставили без изменений ✅", "Kept unchanged ✅"))
    if callback.message is not None:
        await callback.message.edit_reply_markup(reply_markup=None)


@router.callback_query(F.data.startswith("confirm_cancel:"))
async def handle_confirm_cancel_booking(callback: CallbackQuery) -> None:
    locale = await _resolve_locale(None, callback.from_user.id if callback.from_user else None)
    if callback.data is None:
        await callback.answer()
        return

    booking_id = _parse_booking_id(callback.data, "confirm_cancel:")
    if booking_id is None:
        await callback.answer(_t(locale, "Некорректные данные записи", "Invalid booking data"), show_alert=True)
        return

    session_factory = get_session_factory()
    async with session_factory() as session:
        booking, was_cancelled = await cancel_booking_for_client(
            session=session,
            booking_id=booking_id,
            telegram_id=callback.from_user.id,
        )
        service_name = "-"
        client_name = "-"
        client_phone = "-"
        if booking is not None:
            service = await session.get(Service, booking.service_id)
            if service is not None:
                service_name = service.name
            client = await session.get(User, booking.client_id)
            if client is not None:
                client_name = client.full_name or "-"
                client_phone = client.phone or "-"
                locale = normalize_locale(client.locale)

    if booking is None:
        await callback.answer(_t(locale, "Запись не найдена", "Booking not found"), show_alert=True)
        return

    if was_cancelled:
        await callback.answer(_t(locale, "Запись отменена ✅", "Booking cancelled ✅"))
        if callback.message is not None:
            settings = get_settings()
            await _send_visual(
                callback.message,
                sticker_id=settings.telegram_sticker_cancelled,
                fallback_dice="🎳",
            )
            await callback.message.edit_text(
                _spaced(
                    _t(locale, "❌ <b>Запись отменена.</b>", "❌ <b>Booking cancelled.</b>"),
                    _t(locale, "Если захотите, можно создать новую запись в пару нажатий.", "If you want, you can create a new booking in a couple of taps."),
                ),
                reply_markup=None,
            )
        await _notify_managers(
            callback,
            _format_cancelled_booking_manager_message(
                booking_id=booking.id,
                service_name=service_name,
                booking_date=booking.date,
                start_time=booking.start_time,
                client_name=client_name,
                client_phone=client_phone,
                telegram_id=callback.from_user.id,
            ),
        )
        return

    if booking.status == BookingStatus.CANCELLED:
        await callback.answer(_t(locale, "Запись уже была отменена", "Booking was already cancelled"))
        if callback.message is not None:
            await callback.message.edit_text(
                _t(locale, "ℹ️ Запись уже отменена.", "ℹ️ Booking already cancelled."),
                reply_markup=None,
            )
        return

    await callback.answer(
        _t(locale, "Эту запись уже нельзя отменить", "This booking can no longer be cancelled"),
        show_alert=True,
    )


@router.message(F.text.in_(CANCEL_MENU_TEXTS))
async def handle_cancel(message: Message, state: FSMContext) -> None:
    locale = await _resolve_locale(state, message.from_user.id if message.from_user else None)
    await state.set_state(BookingStates.idle)
    await state.update_data(
        locale=locale,
        selected_service_id=None,
        selected_service_name=None,
        selected_date=None,
        selected_slot=None,
        quick_booking=False,
        quick_client_name=None,
        quick_client_phone=None,
        reschedule_booking_id=None,
        reschedule_service_id=None,
        reschedule_service_name=None,
        reschedule_selected_date=None,
    )
    await message.answer(
        _spaced("🛑", _t(locale, "Текущее действие отменено.", "Current action was cancelled.")),
        reply_markup=get_main_menu(locale),
    )
