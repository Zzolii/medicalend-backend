# Path: backend/app/schemas/clinic.py

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, EmailStr


class ClinicBase(BaseModel):
    name: str
    slug: Optional[str] = None

    phone: Optional[str] = None
    email: Optional[EmailStr] = None

    address_line: Optional[str] = None
    city: Optional[str] = None
    county: Optional[str] = None
    postal_code: Optional[str] = None
    country: Optional[str] = "RO"

    is_active: bool = True


class ClinicCreate(ClinicBase):
    pass


class ClinicUpdate(BaseModel):
    name: Optional[str] = None
    slug: Optional[str] = None

    phone: Optional[str] = None
    email: Optional[EmailStr] = None

    address_line: Optional[str] = None
    city: Optional[str] = None
    county: Optional[str] = None
    postal_code: Optional[str] = None
    country: Optional[str] = None

    is_active: Optional[bool] = None


class Clinic(ClinicBase):
    id: int
    created_at: datetime

    class Config:
        from_attributes = True