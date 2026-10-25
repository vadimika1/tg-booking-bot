from __future__ import annotations

from uuid import UUID

from app.bot.handlers.start import _parse_admin_cancel_command

BOOKING_ID = UUID("11111111-2222-3333-4444-555555555555")


def test_parse_admin_cancel_with_pipe() -> None:
    booking_id, reason, error = _parse_admin_cancel_command(
        text="/admin_cancel 11111111-2222-3333-4444-555555555555 | Мастер заболел",
        reply_text=None,
    )
    assert booking_id == BOOKING_ID
    assert reason == "Мастер заболел"
    assert error is None


def test_parse_admin_cancel_reply_mode_without_booking_id_in_command() -> None:
    booking_id, reason, error = _parse_admin_cancel_command(
        text="/admin_cancel Мастер заболел, перенос на завтра",
        reply_text="ID: 11111111-2222-3333-4444-555555555555",
    )
    assert booking_id == BOOKING_ID
    assert reason == "Мастер заболел, перенос на завтра"
    assert error is None


def test_parse_admin_cancel_without_pipe_extracts_uuid_and_reason() -> None:
    booking_id, reason, error = _parse_admin_cancel_command(
        text="/admin_cancel 11111111-2222-3333-4444-555555555555 Мастер заболел",
        reply_text=None,
    )
    assert booking_id == BOOKING_ID
    assert reason == "Мастер заболел"
    assert error is None


def test_parse_admin_cancel_without_uuid_returns_error() -> None:
    booking_id, reason, error = _parse_admin_cancel_command(
        text="/admin_cancel Мастер заболел",
        reply_text=None,
    )
    assert booking_id is None
    assert reason is None
    assert error == "Не найден ID записи. Укажите его в команде или ответьте на карточку записи."


def test_parse_admin_cancel_without_reason_returns_error() -> None:
    booking_id, reason, error = _parse_admin_cancel_command(
        text="/admin_cancel 11111111-2222-3333-4444-555555555555",
        reply_text=None,
    )
    assert booking_id is None
    assert reason is None
    assert error == "Укажите причину отмены (минимум 3 символа)."
