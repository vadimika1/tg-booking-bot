from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class ServiceCreate(BaseModel):
    name: str = Field(min_length=2, max_length=120)
    duration_min: int = Field(ge=5, le=480)
    price: Optional[Decimal] = Field(default=None, ge=0)
    is_active: bool = True


class ServiceUpdate(BaseModel):
    name: Optional[str] = Field(default=None, min_length=2, max_length=120)
    duration_min: Optional[int] = Field(default=None, ge=5, le=480)
    price: Optional[Decimal] = Field(default=None, ge=0)
    is_active: Optional[bool] = None


class ServiceOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str
    duration_min: int
    price: Optional[Decimal]
    is_active: bool
    created_at: datetime
    updated_at: datetime
