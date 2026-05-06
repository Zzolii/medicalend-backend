# Path: backend/app/schemas/dashboard.py

from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel


class DashboardReferral(BaseModel):
    id: int
    episode_id: int
    from_provider_id: int
    to_provider_id: int
    reason: str
    status: str
    created_at: datetime

    class Config:
        from_attributes = True


class DashboardAppointment(BaseModel):
    id: int
    patient_id: int
    provider_id: int
    episode_id: Optional[int] = None
    start_time: datetime
    end_time: Optional[datetime] = None
    status: str
    notes: Optional[str] = None

    class Config:
        from_attributes = True


class ProviderDashboardOut(BaseModel):
    provider_id: int
    pending_referrals: List[DashboardReferral]
    today_appointments: List[DashboardAppointment]
