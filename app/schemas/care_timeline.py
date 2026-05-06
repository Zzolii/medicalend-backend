# Path: backend/app/schemas/care_timeline.py

from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel


class TimelineNote(BaseModel):
    id: int
    author_user_id: int
    text: str
    created_at: datetime

    class Config:
        from_attributes = True


class TimelineTask(BaseModel):
    id: int
    title: str
    due_at: Optional[datetime] = None
    assigned_to_role: Optional[str] = None
    status: str
    created_at: datetime

    class Config:
        from_attributes = True


class TimelineAppointment(BaseModel):
    id: int
    patient_id: int
    provider_id: int
    episode_id: Optional[int] = None
    start_time: datetime
    end_time: Optional[datetime] = None
    status: str
    notes: Optional[str] = None
    created_at: datetime

    class Config:
        from_attributes = True


class TimelineReferral(BaseModel):
    id: int
    episode_id: int
    from_provider_id: int
    to_provider_id: int
    reason: str
    status: str
    rejection_reason: Optional[str] = None
    created_at: datetime

    class Config:
        from_attributes = True


class CareEpisodeTimeline(BaseModel):
    episode_id: int
    notes: List[TimelineNote]
    tasks: List[TimelineTask]
    appointments: List[TimelineAppointment]
    referrals: List[TimelineReferral]
