# Path: backend/app/schemas/subscription.py

from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel


class SubscriptionPlanCreate(BaseModel):
    code: str
    name: str
    description: Optional[str] = None
    price_eur: float
    duration_days: int
    is_active: bool = True


class SubscriptionPlanUpdate(BaseModel):
    code: Optional[str] = None
    name: Optional[str] = None
    description: Optional[str] = None
    price_eur: Optional[float] = None
    duration_days: Optional[int] = None
    is_active: Optional[bool] = None


class SubscriptionPlanOut(BaseModel):
    id: int
    code: Optional[str] = None
    name: Optional[str] = None
    description: Optional[str] = None
    price_eur: Optional[float] = None
    duration_days: Optional[int] = None
    is_active: Optional[bool] = None
    created_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class ClinicSubscriptionCreate(BaseModel):
    clinic_id: int
    plan_id: int
    status: str
    starts_at: datetime
    ends_at: datetime


class ClinicSubscriptionUpdate(BaseModel):
    plan_id: Optional[int] = None
    status: Optional[str] = None
    starts_at: Optional[datetime] = None
    ends_at: Optional[datetime] = None


class ClinicSubscriptionOut(BaseModel):
    id: int
    clinic_id: int
    plan_id: int
    status: str
    starts_at: datetime
    ends_at: datetime
    created_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class ClinicSubscriptionAdminRow(BaseModel):
    id: int
    clinic_id: int
    clinic_name: Optional[str] = None
    plan_id: int
    plan_code: Optional[str] = None
    plan_name: Optional[str] = None
    price_eur: Optional[float] = None
    duration_days: Optional[int] = None
    status: str
    starts_at: datetime
    ends_at: datetime
    created_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class MyClinicSubscriptionOut(BaseModel):
    id: int
    clinic_id: int
    clinic_name: Optional[str] = None
    plan_id: int
    plan_code: Optional[str] = None
    plan_name: Optional[str] = None
    price_eur: Optional[float] = None
    duration_days: Optional[int] = None
    status: str
    starts_at: datetime
    ends_at: datetime
    created_at: Optional[datetime] = None

    class Config:
        from_attributes = True