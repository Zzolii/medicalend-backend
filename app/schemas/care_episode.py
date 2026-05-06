# Path: backend/app/schemas/care_episode.py

from datetime import datetime
from typing import Optional

from pydantic import BaseModel


class CareEpisodeBase(BaseModel):
    patient_id: int
    title: str
    status: str = "open"


class CareEpisodeCreate(BaseModel):
    patient_id: int
    title: str


class CareEpisodeUpdate(BaseModel):
    patient_id: Optional[int] = None
    title: Optional[str] = None
    status: Optional[str] = None  # open/closed


class CareEpisodeOut(CareEpisodeBase):
    id: int
    owner_provider_id: int
    created_at: datetime

    class Config:
        from_attributes = True
