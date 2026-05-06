# Path: backend/app/schemas/clinic_membership.py

from datetime import datetime
from typing import Optional

from pydantic import BaseModel


class ClinicMembershipBase(BaseModel):
    user_id: int
    clinic_id: int
    role: str
    provider_doctor_id: Optional[int] = None
    is_active: bool = True


class ClinicMembershipCreate(ClinicMembershipBase):
    pass


class ClinicMembershipUpdate(BaseModel):
    role: Optional[str] = None
    provider_doctor_id: Optional[int] = None
    is_active: Optional[bool] = None


class ClinicMembership(ClinicMembershipBase):
    id: int
    created_at: datetime

    class Config:
        from_attributes = True