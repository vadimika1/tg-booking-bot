from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import time
from decimal import Decimal

from sqlalchemy import select

from app.infrastructure.db.models import Service, WorkingHours
from app.infrastructure.db.session import get_session_factory


@dataclass(frozen=True)
class DemoService:
    name: str
    duration_min: int
    price: Decimal


DEMO_SERVICES: tuple[DemoService, ...] = (
    DemoService(name="Женская стрижка", duration_min=60, price=Decimal("60")),
    DemoService(name="Мужская стрижка", duration_min=45, price=Decimal("40")),
    DemoService(name="Окрашивание корней", duration_min=90, price=Decimal("110")),
    DemoService(name="Маникюр классический", duration_min=60, price=Decimal("50")),
    DemoService(name="Коррекция бровей", duration_min=30, price=Decimal("30")),
    DemoService(name="Дневной макияж", duration_min=75, price=Decimal("90")),
)


WORKING_HOURS_BY_WEEKDAY: dict[int, tuple[bool, time, time]] = {
    1: (True, time(9, 0), time(20, 0)),
    2: (True, time(9, 0), time(20, 0)),
    3: (True, time(9, 0), time(20, 0)),
    4: (True, time(9, 0), time(20, 0)),
    5: (True, time(9, 0), time(20, 0)),
    6: (True, time(10, 0), time(18, 0)),
    7: (False, time(0, 0), time(0, 0)),
}


async def upsert_services() -> tuple[int, int]:
    created = 0
    updated = 0

    session_factory = get_session_factory()
    async with session_factory() as session:
        result = await session.execute(select(Service))
        existing_by_name = {service.name: service for service in result.scalars().all()}

        for item in DEMO_SERVICES:
            service = existing_by_name.get(item.name)
            if service is None:
                session.add(
                    Service(
                        name=item.name,
                        duration_min=item.duration_min,
                        price=item.price,
                        is_active=True,
                    )
                )
                created += 1
                continue

            service.duration_min = item.duration_min
            service.price = item.price
            service.is_active = True
            updated += 1

        await session.commit()

    return created, updated


async def upsert_working_hours() -> tuple[int, int]:
    created = 0
    updated = 0

    session_factory = get_session_factory()
    async with session_factory() as session:
        result = await session.execute(select(WorkingHours))
        existing_by_weekday = {item.weekday: item for item in result.scalars().all()}

        for weekday, (is_working_day, start_time, end_time) in WORKING_HOURS_BY_WEEKDAY.items():
            item = existing_by_weekday.get(weekday)
            if item is None:
                session.add(
                    WorkingHours(
                        weekday=weekday,
                        start_time=start_time,
                        end_time=end_time,
                        is_working_day=is_working_day,
                    )
                )
                created += 1
                continue

            item.is_working_day = is_working_day
            item.start_time = start_time
            item.end_time = end_time
            updated += 1

        await session.commit()

    return created, updated


async def main() -> None:
    service_created, service_updated = await upsert_services()
    hours_created, hours_updated = await upsert_working_hours()

    print(
        "Demo seed complete: "
        f"services(created={service_created}, updated={service_updated}), "
        f"working_hours(created={hours_created}, updated={hours_updated})"
    )


if __name__ == "__main__":
    asyncio.run(main())
