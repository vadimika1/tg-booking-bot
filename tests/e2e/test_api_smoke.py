from __future__ import annotations

from datetime import date, time, timedelta
from uuid import UUID

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.infrastructure.db.models import Service, User, WorkingHours


@pytest.mark.asyncio
async def test_api_smoke_booking_conflict_and_cancel(
    api_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    service = Service(name="API Smoke Service", duration_min=60, price=2500.00, is_active=True)
    user = User(
        telegram_id=700001,
        full_name="API Smoke Client",
        phone="+79991234567",
    )
    target_date = date.today() + timedelta(days=2)
    weekday = target_date.isoweekday()
    working_hours = WorkingHours(
        weekday=weekday,
        start_time=time(9, 0),
        end_time=time(18, 0),
        is_working_day=True,
    )

    db_session.add_all([service, user, working_hours])
    await db_session.commit()
    await db_session.refresh(service)
    await db_session.refresh(user)

    slots_response = await api_client.get(
        "/api/slots",
        params={"service_id": str(service.id), "date": target_date.isoformat()},
    )
    assert slots_response.status_code == 200
    slots = slots_response.json()
    assert slots

    start_time = slots[0]["start_time"]
    payload = {
        "client_id": str(user.id),
        "service_id": str(service.id),
        "date": target_date.isoformat(),
        "start_time": start_time,
        "source": "test_api_smoke",
    }

    create_response = await api_client.post("/api/bookings", json=payload)
    assert create_response.status_code == 201
    created = create_response.json()
    assert created["status"] == "new"
    booking_id = UUID(created["id"])

    conflict_response = await api_client.post("/api/bookings", json=payload)
    assert conflict_response.status_code == 409

    legacy_cancel_response = await api_client.patch(
        f"/api/bookings/{booking_id}/status",
        json={"status": "cancelled"},
    )
    assert legacy_cancel_response.status_code == 400

    invalid_cancel_response = await api_client.post(
        f"/api/bookings/{booking_id}/admin-cancel",
        json={"reason": "", "notify_client": False},
    )
    assert invalid_cancel_response.status_code == 422

    cancel_response = await api_client.post(
        f"/api/bookings/{booking_id}/admin-cancel",
        json={"reason": "Администратор отменил запись для смены расписания", "notify_client": False},
    )
    assert cancel_response.status_code == 200
    cancelled = cancel_response.json()
    assert cancelled["id"] == str(booking_id)
    assert cancelled["status"] == "cancelled"
    assert "[ADMIN_CANCEL_REASON]" in (cancelled["comment"] or "")
