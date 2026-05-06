# Path: backend/app/schemas/referral.py

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field


class ReferralCreate(BaseModel):
    to_provider_id: int
    reason: str = Field(min_length=3, max_length=2000)


class ReferralReject(BaseModel):
    rejection_reason: str = Field(min_length=3, max_length=2000)


class ReferralOut(BaseModel):
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
