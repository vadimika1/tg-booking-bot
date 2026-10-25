from __future__ import annotations

from datetime import date, datetime, time
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.infrastructure.db.enums import BookingStatus


class BookingCreate(BaseModel):
    client_id: UUID
    service_id: UUID
    date: date
    start_time: time
    end_time: Optional[time] = None
    comment: Optional[str] = Field(default=None, max_length=1000)
    source: str = Field(default="telegram", max_length=64)


class BookingStatusUpdate(BaseModel):
    status: BookingStatus


class BookingAdminCancel(BaseModel):
    reason: str = Field(min_length=3, max_length=500)
    notify_client: bool = True


class BookingOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    client_id: UUID
    service_id: UUID
    date: date
    start_time: time
    end_time: time
    status: BookingStatus
    comment: Optional[str]
    source: str
    created_at: datetime
    updated_at: datetime


class SlotOut(BaseModel):
    start_time: time
    end_time: time
