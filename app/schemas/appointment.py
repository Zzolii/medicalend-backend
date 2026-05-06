# Path: backend/app/schemas/appointment.py

from datetime import datetime
from typing import Optional

from pydantic import BaseModel


class AppointmentBase(BaseModel):
    patient_id: int
    provider_id: int

    doctor_id: Optional[int] = None
    episode_id: Optional[int] = None

    clinic_id: Optional[int] = None
    created_by_user_id: Optional[int] = None

    google_calendar_integration_id: Optional[int] = None
    google_event_id: Optional[str] = None
    google_sync_status: Optional[str] = None
    google_sync_error: Optional[str] = None

    start_time: datetime
    end_time: Optional[datetime] = None
    status: Optional[str] = "scheduled"
    notes: Optional[str] = None
    fhir_id: Optional[str] = None


class AppointmentCreate(AppointmentBase):
    patient_id: int
    provider_id: int
    start_time: datetime


class AppointmentUpdate(BaseModel):
    provider_id: Optional[int] = None
    doctor_id: Optional[int] = None
    episode_id: Optional[int] = None

    clinic_id: Optional[int] = None
    created_by_user_id: Optional[int] = None

    google_calendar_integration_id: Optional[int] = None
    google_event_id: Optional[str] = None
    google_sync_status: Optional[str] = None
    google_sync_error: Optional[str] = None

    start_time: Optional[datetime] = None
    end_time: Optional[datetime] = None
    status: Optional[str] = None
    notes: Optional[str] = None
    fhir_id: Optional[str] = None


class AppointmentInDBBase(AppointmentBase):
    id: int
    created_at: datetime

    patient_name: Optional[str] = None
    provider_name: Optional[str] = None
    doctor_name: Optional[str] = None

    class Config:
        from_attributes = True


class Appointment(AppointmentInDBBase):
    pass