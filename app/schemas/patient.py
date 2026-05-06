# Path: backend/app/schemas/patient.py
from datetime import date, datetime
from typing import Optional

from pydantic import BaseModel, EmailStr, ConfigDict


class PatientBase(BaseModel):
    fhir_id: Optional[str] = None

    user_id: Optional[int] = None

    first_name: str
    last_name: str
    birth_date: Optional[date] = None
    gender: Optional[str] = None

    phone: Optional[str] = None
    email: Optional[EmailStr] = None
    address_line: Optional[str] = None
    city: Optional[str] = None
    county: Optional[str] = None
    postal_code: Optional[str] = None
    country: Optional[str] = "RO"


class PatientCreate(PatientBase):
    pass


class PatientUpdate(BaseModel):
    fhir_id: Optional[str] = None

    first_name: Optional[str] = None
    last_name: Optional[str] = None
    birth_date: Optional[date] = None
    gender: Optional[str] = None

    phone: Optional[str] = None
    email: Optional[EmailStr] = None
    address_line: Optional[str] = None
    city: Optional[str] = None
    county: Optional[str] = None
    postal_code: Optional[str] = None
    country: Optional[str] = None


class Patient(PatientBase):
    model_config = ConfigDict(from_attributes=True)

    id: int
    created_at: datetime


# ✅ OUT schema (response_model-hez)
# Most MVP-ben legyen ugyanaz, mint a Patient.
class PatientOut(Patient):
    pass
