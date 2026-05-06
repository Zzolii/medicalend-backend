# Path: backend/app/schemas/care_task.py

from datetime import datetime
from typing import Optional

from pydantic import BaseModel


class CareTaskCreate(BaseModel):
    title: str
    due_at: Optional[datetime] = None
    assigned_to_role: str = "provider"  # provider/patient


class CareTaskUpdate(BaseModel):
    title: Optional[str] = None
    due_at: Optional[datetime] = None
    status: Optional[str] = None  # todo/doing/done
    assigned_to_role: Optional[str] = None


class CareTaskOut(BaseModel):
    id: int
    episode_id: int

    # ✅ NEW
    appointment_id: Optional[int] = None

    title: str
    due_at: Optional[datetime] = None
    status: str
    assigned_to_role: str
    created_at: datetime

    class Config:
        from_attributes = True