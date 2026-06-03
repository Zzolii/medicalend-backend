# Path: backend/app/schemas/home_care.py

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, field_validator


class HomeCareCaseCreate(BaseModel):
    patient_id: int
    title: str
    clinic_id: Optional[int] = None
    owner_provider_id: Optional[int] = None

    address_line: Optional[str] = None
    city: Optional[str] = None
    county: Optional[str] = None
    contact_phone: Optional[str] = None
    care_plan: Optional[str] = None

    @field_validator("title")
    @classmethod
    def validate_title(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("Titlul cazului Home Care este obligatoriu.")
        return cleaned


class HomeCareCaseUpdate(BaseModel):
    title: Optional[str] = None
    status: Optional[str] = None

    address_line: Optional[str] = None
    city: Optional[str] = None
    county: Optional[str] = None
    contact_phone: Optional[str] = None
    care_plan: Optional[str] = None

    @field_validator("title")
    @classmethod
    def validate_optional_title(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return value

        cleaned = value.strip()
        if not cleaned:
            raise ValueError("Titlul cazului Home Care nu poate fi gol.")
        return cleaned


class HomeCareCaseOut(BaseModel):
    id: int
    patient_id: int
    clinic_id: Optional[int] = None
    owner_provider_id: Optional[int] = None

    title: str
    status: str

    address_line: Optional[str] = None
    city: Optional[str] = None
    county: Optional[str] = None
    contact_phone: Optional[str] = None
    care_plan: Optional[str] = None

    created_by_user_id: Optional[int] = None
    created_at: datetime

    class Config:
        from_attributes = True


class HomeCareVisitCreate(BaseModel):
    case_id: int
    scheduled_at: datetime

    assigned_user_id: Optional[int] = None

    blood_pressure: Optional[str] = None
    blood_sugar: Optional[str] = None
    pulse: Optional[str] = None
    temperature: Optional[str] = None
    oxygen_saturation: Optional[str] = None
    note: Optional[str] = None


class HomeCareVisitUpdate(BaseModel):
    scheduled_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None

    assigned_user_id: Optional[int] = None
    performed_by_user_id: Optional[int] = None

    status: Optional[str] = None

    blood_pressure: Optional[str] = None
    blood_sugar: Optional[str] = None
    pulse: Optional[str] = None
    temperature: Optional[str] = None
    oxygen_saturation: Optional[str] = None
    note: Optional[str] = None


class HomeCareVisitOut(BaseModel):
    id: int

    case_id: int
    patient_id: int
    clinic_id: Optional[int] = None

    scheduled_at: datetime
    completed_at: Optional[datetime] = None

    assigned_user_id: Optional[int] = None
    performed_by_user_id: Optional[int] = None

    status: str

    blood_pressure: Optional[str] = None
    blood_sugar: Optional[str] = None
    pulse: Optional[str] = None
    temperature: Optional[str] = None
    oxygen_saturation: Optional[str] = None
    note: Optional[str] = None

    created_by_user_id: Optional[int] = None
    created_at: datetime

    class Config:
        from_attributes = True