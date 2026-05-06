# Path: backend/app/schemas/user.py

from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, EmailStr, Field


class UserBase(BaseModel):
    email: EmailStr
    role: str = "provider"
    is_active: bool = True
    is_email_verified: bool = False
    email_verified_at: Optional[datetime] = None


class UserCreate(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=64)


class UserUpdate(BaseModel):
    email: Optional[EmailStr] = None
    role: Optional[str] = None
    is_active: Optional[bool] = None
    password: Optional[str] = Field(default=None, min_length=8, max_length=64)


class ClinicMembershipOut(BaseModel):
    id: int
    clinic_id: int
    role: str
    provider_doctor_id: Optional[int] = None
    is_active: bool
    created_at: datetime

    class Config:
        from_attributes = True


class User(UserBase):
    id: int
    created_at: datetime

    class Config:
        from_attributes = True


class UserWithMemberships(User):
    clinic_memberships: List[ClinicMembershipOut] = []


class ClinicStaffCreate(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=64)
    clinic_role: str = Field(min_length=3, max_length=50)
    provider_doctor_id: Optional[int] = None
    is_active: bool = True


class ClinicStaffUpdate(BaseModel):
    email: Optional[EmailStr] = None
    clinic_role: Optional[str] = Field(default=None, min_length=3, max_length=50)
    provider_doctor_id: Optional[int] = None
    is_active: Optional[bool] = None
    password: Optional[str] = Field(default=None, min_length=8, max_length=64)


class ClinicStaffRow(BaseModel):
    user_id: int
    email: EmailStr
    global_role: str
    user_is_active: bool

    membership_id: int
    clinic_id: int
    clinic_role: str
    provider_doctor_id: Optional[int] = None
    provider_doctor_name: Optional[str] = None
    membership_is_active: bool

    created_at: datetime

    class Config:
        from_attributes = True