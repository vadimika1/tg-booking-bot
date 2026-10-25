from __future__ import annotations

from app.bot.localization import (
    LOCALE_EN,
    LOCALE_RU,
    booking_status_label,
    duration_with_unit,
    menu_label,
    normalize_locale,
)
from app.infrastructure.db.enums import BookingStatus


def test_normalize_locale_falls_back_to_ru() -> None:
    assert normalize_locale(None) == LOCALE_RU
    assert normalize_locale("de") == LOCALE_RU


def test_menu_label_en() -> None:
    assert menu_label(LOCALE_EN, "book") == "✨ Book now"
    assert menu_label(LOCALE_EN, "language") == "🌐 Language"


def test_booking_status_label_en() -> None:
    assert booking_status_label(BookingStatus.CONFIRMED, LOCALE_EN) == "Confirmed"


def test_duration_with_unit_is_localized() -> None:
    assert duration_with_unit(45, LOCALE_RU) == "45 мин"
    assert duration_with_unit(45, LOCALE_EN) == "45 min"
