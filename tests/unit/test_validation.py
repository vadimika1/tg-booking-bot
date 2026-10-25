from __future__ import annotations

from app.application.use_cases.validation import normalize_phone_ru, validate_full_name


def test_normalize_phone_ru_with_plus7() -> None:
    assert normalize_phone_ru("+7 (999) 123-45-67") == "+79991234567"


def test_normalize_phone_ru_with_8_prefix() -> None:
    assert normalize_phone_ru("8 999 123 45 67") == "+79991234567"


def test_normalize_phone_ru_with_10_digits_mobile() -> None:
    assert normalize_phone_ru("9991234567") == "+79991234567"


def test_normalize_phone_ru_rejects_invalid() -> None:
    assert normalize_phone_ru("12345") is None


def test_validate_full_name_normalizes_spaces() -> None:
    assert validate_full_name("  Иван   Петров  ") == "Иван Петров"


def test_validate_full_name_rejects_too_short() -> None:
    assert validate_full_name("A") is None


def test_validate_full_name_rejects_too_long() -> None:
    assert validate_full_name("x" * 61) is None
