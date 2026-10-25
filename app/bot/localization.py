from __future__ import annotations

from app.infrastructure.db.enums import BookingStatus

LOCALE_RU = "ru"
LOCALE_EN = "en"
DEFAULT_LOCALE = LOCALE_RU
SUPPORTED_LOCALES = {LOCALE_RU, LOCALE_EN}

_MAIN_MENU: dict[str, dict[str, str]] = {
    LOCALE_RU: {
        "book": "✨ Записаться",
        "quick": "⚡ Быстрая запись",
        "my_bookings": "📋 Мои записи",
        "cancel": "🛑 Отмена",
        "language": "🌐 Язык",
    },
    LOCALE_EN: {
        "book": "✨ Book now",
        "quick": "⚡ Quick booking",
        "my_bookings": "📋 My bookings",
        "cancel": "🛑 Cancel",
        "language": "🌐 Language",
    },
}

MAIN_MENU_TEXT_MATCHES: dict[str, set[str]] = {
    "book": {"Записаться", "✨ Записаться", "Book now", "✨ Book now"},
    "quick": {"Быстрая запись", "⚡ Быстрая запись", "Quick booking", "⚡ Quick booking"},
    "my_bookings": {"Мои записи", "📋 Мои записи", "My bookings", "📋 My bookings"},
    "cancel": {"Отмена", "🛑 Отмена", "Cancel", "🛑 Cancel"},
    "language": {"Язык", "🌐 Язык", "Language", "🌐 Language"},
}

_INLINE_TEXTS: dict[str, dict[str, str]] = {
    LOCALE_RU: {
        "cancel_flow": "✖️ Отмена",
        "back_services": "⬅️ Назад к услугам",
        "back_dates": "⬅️ Назад к датам",
        "waitlist_join": "🔔 В лист ожидания",
        "choose_other_date": "⬅️ Выбрать другую дату",
        "confirm_booking": "✅ Подтвердить запись",
        "back_slots": "⬅️ Назад к слотам",
        "cancel_booking": "❌ Отменить запись",
        "reschedule_booking": "🔁 Перенести запись",
        "confirm_cancel_yes": "✅ Да, отменить",
        "confirm_cancel_keep": "↩️ Оставить как есть",
        "reschedule_back_list": "⬅️ К моим записям",
        "reminder_confirm": "✅ Приду",
        "reminder_decline": "❌ Не приду",
    },
    LOCALE_EN: {
        "cancel_flow": "✖️ Cancel",
        "back_services": "⬅️ Back to services",
        "back_dates": "⬅️ Back to dates",
        "waitlist_join": "🔔 Join waitlist",
        "choose_other_date": "⬅️ Pick another date",
        "confirm_booking": "✅ Confirm booking",
        "back_slots": "⬅️ Back to slots",
        "cancel_booking": "❌ Cancel booking",
        "reschedule_booking": "🔁 Reschedule booking",
        "confirm_cancel_yes": "✅ Yes, cancel",
        "confirm_cancel_keep": "↩️ Keep as is",
        "reschedule_back_list": "⬅️ Back to my bookings",
        "reminder_confirm": "✅ I will come",
        "reminder_decline": "❌ I can't come",
    },
}

_WEEKDAY_LABELS: dict[str, dict[int, str]] = {
    LOCALE_RU: {
        1: "Пн",
        2: "Вт",
        3: "Ср",
        4: "Чт",
        5: "Пт",
        6: "Сб",
        7: "Вс",
    },
    LOCALE_EN: {
        1: "Mon",
        2: "Tue",
        3: "Wed",
        4: "Thu",
        5: "Fri",
        6: "Sat",
        7: "Sun",
    },
}

_STATUS_LABELS: dict[str, dict[BookingStatus, str]] = {
    LOCALE_RU: {
        BookingStatus.NEW: "Новая",
        BookingStatus.CONFIRMED: "Подтверждена",
        BookingStatus.DONE: "Завершена",
        BookingStatus.CANCELLED: "Отменена",
        BookingStatus.NO_SHOW: "Клиент не пришёл",
    },
    LOCALE_EN: {
        BookingStatus.NEW: "New",
        BookingStatus.CONFIRMED: "Confirmed",
        BookingStatus.DONE: "Done",
        BookingStatus.CANCELLED: "Cancelled",
        BookingStatus.NO_SHOW: "No-show",
    },
}


def normalize_locale(raw: str | None) -> str:
    if not raw:
        return DEFAULT_LOCALE
    value = raw.strip().lower()
    if value in SUPPORTED_LOCALES:
        return value
    return DEFAULT_LOCALE


def menu_label(locale: str, key: str) -> str:
    lang = normalize_locale(locale)
    return _MAIN_MENU[lang][key]


def inline_text(locale: str, key: str) -> str:
    lang = normalize_locale(locale)
    return _INLINE_TEXTS[lang][key]


def weekday_label(weekday: int, locale: str) -> str:
    lang = normalize_locale(locale)
    return _WEEKDAY_LABELS[lang].get(weekday, "")


def booking_status_label(status: BookingStatus, locale: str) -> str:
    lang = normalize_locale(locale)
    return _STATUS_LABELS[lang].get(status, status.value)


def duration_with_unit(minutes: int, locale: str) -> str:
    lang = normalize_locale(locale)
    if lang == LOCALE_EN:
        return f"{minutes} min"
    return f"{minutes} мин"
