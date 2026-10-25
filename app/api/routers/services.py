from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.schemas import ServiceCreate, ServiceOut, ServiceUpdate
from app.infrastructure.db.models import Service
from app.infrastructure.db.session import get_db_session

router = APIRouter(prefix="/api/services", tags=["services"])


@router.get("", response_model=list[ServiceOut])
async def list_services(
    include_inactive: bool = False,
    session: AsyncSession = Depends(get_db_session),
) -> list[Service]:
    query = select(Service)
    if not include_inactive:
        query = query.where(Service.is_active.is_(True))

    result = await session.execute(query.order_by(Service.name.asc()))
    return list(result.scalars().all())


@router.post("", response_model=ServiceOut, status_code=status.HTTP_201_CREATED)
async def create_service(
    payload: ServiceCreate,
    session: AsyncSession = Depends(get_db_session),
) -> Service:
    service = Service(
        name=payload.name.strip(),
        duration_min=payload.duration_min,
        price=payload.price,
        is_active=payload.is_active,
    )
    session.add(service)
    await session.commit()
    await session.refresh(service)
    return service


@router.patch("/{service_id}", response_model=ServiceOut)
async def update_service(
    service_id: UUID,
    payload: ServiceUpdate,
    session: AsyncSession = Depends(get_db_session),
) -> Service:
    service = await session.get(Service, service_id)
    if service is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Service not found")

    update_data = payload.model_dump(exclude_unset=True)
    if "name" in update_data and update_data["name"] is not None:
        update_data["name"] = update_data["name"].strip()

    for key, value in update_data.items():
        setattr(service, key, value)

    await session.commit()
    await session.refresh(service)
    return service
