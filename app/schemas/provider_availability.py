# Path: backend/app/schemas/provider_availability.py

from datetime import date, datetime, time
from typing import Optional

from pydantic import BaseModel, Field, field_validator

ALLOWED_SLOT_DURATIONS = {5, 10, 15, 20, 30}


class ProviderAvailabilityBase(BaseModel):
    weekday: int = Field(..., ge=0, le=6)
    start_time: time
    end_time: time
    doctor_id: Optional[int] = None
    slot_duration_minutes: int = 30

    @field_validator("slot_duration_minutes")
    @classmethod
    def validate_slot_duration(cls, value: int) -> int:
        if value not in ALLOWED_SLOT_DURATIONS:
            raise ValueError("slot_duration_minutes must be one of: 5, 10, 15, 20, 30")
        return value


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