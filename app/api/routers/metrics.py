from __future__ import annotations

from datetime import date, datetime, timezone

from fastapi import APIRouter, Depends, Request
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.infrastructure.db.enums import BookingStatus, NotificationStatus
from app.infrastructure.db.models import Booking, Notification
from app.infrastructure.db.session import get_db_session

router = APIRouter(tags=["metrics"])


@router.get("/metrics")
async def get_metrics(
    request: Request,
    session: AsyncSession = Depends(get_db_session),
) -> dict[str, int | float | str]:
    today = date.today()
    now = datetime.now(timezone.utc)
    started_at: datetime = request.app.state.started_at

    bookings_today_result = await session.execute(
        select(func.count(Booking.id)).where(Booking.date == today)
    )
    cancellations_today_result = await session.execute(
        select(func.count(Booking.id)).where(
            Booking.date == today,
            Booking.status == BookingStatus.CANCELLED,
        )
    )
    pending_notifications_result = await session.execute(
        select(func.count(Notification.id)).where(
            Notification.status == NotificationStatus.PENDING
        )
    )
    failed_notifications_result = await session.execute(
        select(func.count(Notification.id)).where(
            Notification.status == NotificationStatus.FAILED
        )
    )
    sent_notifications_today_result = await session.execute(
        select(func.count(Notification.id)).where(
            Notification.status == NotificationStatus.SENT,
            Notification.sent_at >= datetime.combine(today, datetime.min.time(), tzinfo=timezone.utc),
        )
    )

    return {
        "bookings_today": int(bookings_today_result.scalar_one()),
        "cancellations_today": int(cancellations_today_result.scalar_one()),
        "notifications_pending": int(pending_notifications_result.scalar_one()),
        "notifications_failed": int(failed_notifications_result.scalar_one()),
        "notifications_sent_today": int(sent_notifications_today_result.scalar_one()),
        "api_uptime_sec": round((now - started_at).total_seconds(), 2),
        "timestamp": now.isoformat(),
    }
