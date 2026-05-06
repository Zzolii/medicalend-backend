# Path: backend/app/schemas/provider_availability.py

from datetime import time, date, datetime
from typing import Optional

from pydantic import BaseModel


class ProviderAvailabilityBase(BaseModel):
    weekday: int
    start_time: time
    end_time: time
    doctor_id: Optional[int] = None


class ProviderAvailabilityCreate(ProviderAvailabilityBase):
    pass


class ProviderAvailabilityOut(ProviderAvailabilityBase):
    id: int
    provider_id: int
    is_active: bool

    class Config:
        from_attributes = True


class ProviderAvailabilityExceptionBase(BaseModel):
    date: date
    is_closed: bool = False
    start_time: Optional[time] = None
    end_time: Optional[time] = None
    note: Optional[str] = None
    doctor_id: Optional[int] = None


class ProviderAvailabilityExceptionCreate(ProviderAvailabilityExceptionBase):
    pass


class ProviderAvailabilityExceptionOut(ProviderAvailabilityExceptionBase):
    id: int
    provider_id: int

    class Config:
        from_attributes = True


class ProviderAvailabilityExceptionDeleteOut(BaseModel):
    ok: bool = True
    id: int
    deleted_at: datetime