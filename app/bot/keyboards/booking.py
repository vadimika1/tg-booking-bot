from __future__ import annotations

from datetime import date, time
from typing import Iterable
from uuid import UUID

from aiogram.types import InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from app.bot.localization import (
    LOCALE_RU,
    duration_with_unit,
    inline_text,
    normalize_locale,
    weekday_label,
)
from app.infrastructure.db.models import Service


def build_services_keyboard(
    services: Iterable[Service],
    locale: str = LOCALE_RU,
) -> InlineKeyboardMarkup:
    lang = normalize_locale(locale)
    builder = InlineKeyboardBuilder()
    for service in services:
        label = f"🧾 {service.name} · {duration_with_unit(service.duration_min, lang)}"
        builder.button(text=label, callback_data=f"service:{service.id}")
    builder.button(text=inline_text(lang, "cancel_flow"), callback_data="flow:cancel")
    builder.adjust(1)
    return builder.as_markup()


def build_dates_keyboard(
    dates: Iterable[date],
    locale: str = LOCALE_RU,
) -> InlineKeyboardMarkup:
    lang = normalize_locale(locale)
    builder = InlineKeyboardBuilder()
    for item in dates:
        weekday = weekday_label(item.isoweekday(), lang)
        builder.button(
            text=f"📅 {item.strftime('%d.%m')} ({weekday})",
            callback_data=f"date:{item.isoformat()}",
        )
    builder.button(text=inline_text(lang, "back_services"), callback_data="back:services")
    builder.button(text=inline_text(lang, "cancel_flow"), callback_data="flow:cancel")
    builder.adjust(2, 2, 2, 1)
    return builder.as_markup()


def build_slots_keyboard(
    slots: Iterable[tuple[time, time]],
    locale: str = LOCALE_RU,
) -> InlineKeyboardMarkup:
    lang = normalize_locale(locale)
    builder = InlineKeyboardBuilder()
    for start_time, end_time in slots:
        label = f"🕒 {start_time.strftime('%H:%M')} - {end_time.strftime('%H:%M')}"
        builder.button(text=label, callback_data=f"slot:{start_time.strftime('%H:%M')}")
    builder.button(text=inline_text(lang, "back_dates"), callback_data="back:dates")
    builder.button(text=inline_text(lang, "cancel_flow"), callback_data="flow:cancel")
    builder.adjust(2, 2, 2, 1)
    return builder.as_markup()


def build_waitlist_offer_keyboard(locale: str = LOCALE_RU) -> InlineKeyboardMarkup:
    lang = normalize_locale(locale)
    builder = InlineKeyboardBuilder()
    builder.button(text=inline_text(lang, "waitlist_join"), callback_data="waitlist:join")
    builder.button(text=inline_text(lang, "choose_other_date"), callback_data="back:dates")
    builder.button(text=inline_text(lang, "cancel_flow"), callback_data="flow:cancel")
    builder.adjust(1)
    return builder.as_markup()


def build_confirmation_keyboard(locale: str = LOCALE_RU) -> InlineKeyboardMarkup:
    lang = normalize_locale(locale)
    builder = InlineKeyboardBuilder()
    builder.button(text=inline_text(lang, "confirm_booking"), callback_data="confirm:booking")
    builder.button(text=inline_text(lang, "back_slots"), callback_data="back:slots")
    builder.button(text=inline_text(lang, "cancel_flow"), callback_data="flow:cancel")
    builder.adjust(1)
    return builder.as_markup()


def build_booking_cancel_keyboard(
    booking_id: UUID,
    locale: str = LOCALE_RU,
) -> InlineKeyboardMarkup:
    lang = normalize_locale(locale)
    builder = InlineKeyboardBuilder()
    builder.button(text=inline_text(lang, "cancel_booking"), callback_data=f"cancel_booking:{booking_id}")
    return builder.as_markup()


def build_booking_actions_keyboard(
    booking_id: UUID,
    locale: str = LOCALE_RU,
) -> InlineKeyboardMarkup:
    lang = normalize_locale(locale)
    builder = InlineKeyboardBuilder()
    builder.button(
        text=inline_text(lang, "reschedule_booking"),
        callback_data=f"reschedule_booking:{booking_id}",
    )
    builder.button(text=inline_text(lang, "cancel_booking"), callback_data=f"cancel_booking:{booking_id}")
    builder.adjust(1)
    return builder.as_markup()


def build_cancel_confirmation_keyboard(
    booking_id: UUID,
    locale: str = LOCALE_RU,
) -> InlineKeyboardMarkup:
    lang = normalize_locale(locale)
    builder = InlineKeyboardBuilder()
    builder.button(text=inline_text(lang, "confirm_cancel_yes"), callback_data=f"confirm_cancel:{booking_id}")
    builder.button(text=inline_text(lang, "confirm_cancel_keep"), callback_data="keep_booking")
    builder.adjust(1)
    return builder.as_markup()


def build_reschedule_dates_keyboard(
    dates: Iterable[date],
    locale: str = LOCALE_RU,
) -> InlineKeyboardMarkup:
    lang = normalize_locale(locale)
    builder = InlineKeyboardBuilder()
    for item in dates:
        weekday = weekday_label(item.isoweekday(), lang)
        builder.button(
            text=f"📅 {item.strftime('%d.%m')} ({weekday})",
            callback_data=f"reschedule_date:{item.isoformat()}",
        )
    builder.button(text=inline_text(lang, "reschedule_back_list"), callback_data="reschedule_back:list")
    builder.button(text=inline_text(lang, "cancel_flow"), callback_data="flow:cancel")
    builder.adjust(2, 2, 2, 1)
    return builder.as_markup()


def build_reschedule_slots_keyboard(
    slots: Iterable[tuple[time, time]],
    locale: str = LOCALE_RU,
) -> InlineKeyboardMarkup:
    lang = normalize_locale(locale)
    builder = InlineKeyboardBuilder()
    for start_time, end_time in slots:
        label = f"🕒 {start_time.strftime('%H:%M')} - {end_time.strftime('%H:%M')}"
        builder.button(
            text=label,
            callback_data=f"reschedule_slot:{start_time.strftime('%H:%M')}",
        )
    builder.button(text=inline_text(lang, "back_dates"), callback_data="reschedule_back:dates")
    builder.button(text=inline_text(lang, "cancel_flow"), callback_data="flow:cancel")
    builder.adjust(2, 2, 2, 1)
    return builder.as_markup()


def build_reminder_confirmation_keyboard(
    booking_id: UUID,
    locale: str = LOCALE_RU,
) -> InlineKeyboardMarkup:
    lang = normalize_locale(locale)
    builder = InlineKeyboardBuilder()
    builder.button(text=inline_text(lang, "reminder_confirm"), callback_data=f"reminder_confirm:{booking_id}")
    builder.button(text=inline_text(lang, "reminder_decline"), callback_data=f"reminder_decline:{booking_id}")
    builder.adjust(2)
    return builder.as_markup()
