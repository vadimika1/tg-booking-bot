from __future__ import annotations

from datetime import date, datetime

from app.worker.main import (
    DailyReportStats,
    _build_daily_report_text,
    _should_send_daily_report_now,
)


def test_should_send_daily_report_only_after_planned_time() -> None:
    before_time = datetime(2026, 3, 3, 19, 59, 59)
    at_time = datetime(2026, 3, 3, 20, 0, 0)
    after_time = datetime(2026, 3, 3, 20, 5, 0)

    assert _should_send_daily_report_now(before_time, 20, 0) is False
    assert _should_send_daily_report_now(at_time, 20, 0) is True
    assert _should_send_daily_report_now(after_time, 20, 0) is True


def test_build_daily_report_text_contains_main_metrics() -> None:
    stats = DailyReportStats(
        report_date=date(2026, 3, 3),
        total=10,
        new_count=3,
        confirmed_count=2,
        done_count=4,
        cancelled_count=1,
        no_show_count=0,
        waitlist_count=2,
        tomorrow_total=5,
        tomorrow_active_count=4,
    )

    text = _build_daily_report_text(stats, "Europe/Minsk")

    assert "Ежедневный отчёт" in text
    assert "03.03.2026" in text
    assert "Записей на сегодня: <b>10</b>" in text
    assert "Новые: <b>3</b>" in text
    assert "Лист ожидания на сегодня: <b>2</b>" in text
    assert "На завтра активных (new/confirmed): <b>4</b>" in text
