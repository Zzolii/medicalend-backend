# Path: backend/app/schemas/provider_structure.py

from datetime import datetime
from typing import Optional, List

from pydantic import BaseModel, Field, EmailStr


class ProviderSpecialtyCreate(BaseModel):
    name: str = Field(min_length=2, max_length=120)


class ProviderSpecialtyUpdate(BaseModel):
    name: Optional[str] = Field(default=None, min_length=2, max_length=120)
    is_active: Optional[bool] = None


class ProviderSpecialtyOut(BaseModel):
    id: int
    provider_id: int
    name: str
    is_active: bool
    created_at: datetime

    class Config:
        from_attributes = True


class ProviderDoctorCreate(BaseModel):
    specialty_id: int
    name: str = Field(min_length=2, max_length=120)
    title: Optional[str] = Field(default=None, max_length=80)
    license_number: Optional[str] = Field(default=None, max_length=120)
    phone: Optional[str] = Field(default=None, max_length=50)
    email: Optional[EmailStr] = None


class ProviderDoctorUpdate(BaseModel):
    specialty_id: Optional[int] = None
    name: Optional[str] = Field(default=None, min_length=2, max_length=120)
    title: Optional[str] = Field(default=None, max_length=80)
    license_number: Optional[str] = Field(default=None, max_length=120)
    phone: Optional[str] = Field(default=None, max_length=50)
    email: Optional[EmailStr] = None
    is_active: Optional[bool] = None


class ProviderDoctorOut(BaseModel):
    id: int
    provider_id: int
    specialty_id: int
    name: str
    title: Optional[str] = None
    license_number: Optional[str] = None
    phone: Optional[str] = None
    email: Optional[EmailStr] = None
    is_active: bool
    created_at: datetime

    class Config:
        from_attributes = True


class ProviderDoctorExpandedOut(ProviderDoctorOut):
    specialty_name: Optional[str] = None


class ProviderStructureOut(BaseModel):
    specialties: List[ProviderSpecialtyOut]
    doctors: List[ProviderDoctorExpandedOut]