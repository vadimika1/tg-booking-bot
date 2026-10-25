from __future__ import annotations

from datetime import time
from decimal import Decimal
from typing import Optional
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.infrastructure.db.models import Service, WorkingHours


async def list_services_for_admin(
    session: AsyncSession,
    *,
    include_inactive: bool = True,
) -> list[Service]:
    query = select(Service)
    if not include_inactive:
        query = query.where(Service.is_active.is_(True))
    query = query.order_by(Service.is_active.desc(), Service.name.asc())
    result = await session.execute(query)
    return list(result.scalars().all())


async def create_service_by_admin(
    session: AsyncSession,
    *,
    name: str,
    duration_min: int,
    price: Optional[Decimal],
) -> Service:
    service = Service(
        name=name,
        duration_min=duration_min,
        price=price,
        is_active=True,
    )
    session.add(service)
    await session.commit()
    await session.refresh(service)
    return service


async def update_service_by_admin(
    session: AsyncSession,
    *,
    service_id: UUID,
    name: Optional[str] = None,
    duration_min: Optional[int] = None,
    price: Optional[Decimal] = None,
    is_active: Optional[bool] = None,
) -> Optional[Service]:
    service = await session.get(Service, service_id)
    if service is None:
        return None

    if name is not None:
        service.name = name
    if duration_min is not None:
        service.duration_min = duration_min
    if price is not None:
        service.price = price
    if is_active is not None:
        service.is_active = is_active

    await session.commit()
    await session.refresh(service)
    return service


async def deactivate_service_by_admin(
    session: AsyncSession,
    *,
    service_id: UUID,
) -> Optional[Service]:
    service = await session.get(Service, service_id)
    if service is None:
        return None
    service.is_active = False
    await session.commit()
    await session.refresh(service)
    return service


async def list_working_hours_for_admin(session: AsyncSession) -> list[WorkingHours]:
    result = await session.execute(select(WorkingHours).order_by(WorkingHours.weekday.asc()))
    return list(result.scalars().all())


async def set_working_hours_for_admin(
    session: AsyncSession,
    *,
    weekday: int,
    start_time: time,
    end_time: time,
) -> WorkingHours:
    result = await session.execute(select(WorkingHours).where(WorkingHours.weekday == weekday))
    row = result.scalar_one_or_none()
    if row is None:
        row = WorkingHours(
            weekday=weekday,
            start_time=start_time,
            end_time=end_time,
            is_working_day=True,
        )
        session.add(row)
    else:
        row.start_time = start_time
        row.end_time = end_time
        row.is_working_day = True

    await session.commit()
    await session.refresh(row)
    return row


async def set_working_day_off_by_admin(
    session: AsyncSession,
    *,
    weekday: int,
) -> WorkingHours:
    result = await session.execute(select(WorkingHours).where(WorkingHours.weekday == weekday))
    row = result.scalar_one_or_none()
    if row is None:
        row = WorkingHours(
            weekday=weekday,
            start_time=time(9, 0),
            end_time=time(18, 0),
            is_working_day=False,
        )
        session.add(row)
    else:
        row.is_working_day = False

    await session.commit()
    await session.refresh(row)
    return row


async def delete_working_hours_by_admin(
    session: AsyncSession,
    *,
    weekday: int,
) -> bool:
    result = await session.execute(select(WorkingHours).where(WorkingHours.weekday == weekday))
    row = result.scalar_one_or_none()
    if row is None:
        return False
    await session.delete(row)
    await session.commit()
    return True
