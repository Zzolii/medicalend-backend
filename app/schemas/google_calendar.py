# Path: backend/app/schemas/google_calendar.py

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field


class GoogleCalendarIntegrationCreate(BaseModel):
    provider_id: int
    doctor_id: Optional[int] = None

    google_calendar_id: str = Field(min_length=3, max_length=500)
    google_calendar_name: Optional[str] = Field(default=None, max_length=200)
    google_account_email: Optional[str] = Field(default=None, max_length=320)

    sync_direction: str = "google_bridge"


class GoogleCalendarIntegrationUpdate(BaseModel):
    google_calendar_id: Optional[str] = Field(default=None, min_length=3, max_length=500)
    google_calendar_name: Optional[str] = Field(default=None, max_length=200)
    google_account_email: Optional[str] = Field(default=None, max_length=320)
    sync_direction: Optional[str] = None
    status: Optional[str] = None
    is_active: Optional[bool] = None


class GoogleCalendarIntegrationOut(BaseModel):
    id: int
    clinic_id: int
    provider_id: int
    doctor_id: Optional[int] = None

    google_account_email: Optional[str] = None
    google_calendar_id: str
    google_calendar_name: Optional[str] = None

    sync_direction: str
    status: str
    is_active: bool

    last_sync_at: Optional[datetime] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class GoogleCalendarFreeBusyTestIn(BaseModel):
    time_min: datetime
    time_max: datetime


class GoogleCalendarBusySlot(BaseModel):
    start: datetime
    end: datetime


class GoogleCalendarFreeBusyTestOut(BaseModel):
    configured: bool
    calendar_id: str
    busy: list[GoogleCalendarBusySlot] = []
    message: Optional[str] = None