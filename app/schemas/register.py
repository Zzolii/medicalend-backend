# Path: backend/app/schemas/register.py

from datetime import date
from typing import Literal, Optional

from pydantic import BaseModel, EmailStr, Field


ProviderType = Literal["clinic", "home_care"]


class RegisterPatientRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=64)

    first_name: str = Field(min_length=1, max_length=80)
    last_name: str = Field(min_length=1, max_length=80)

    birth_date: Optional[date] = None
    gender: Optional[str] = None

    phone: Optional[str] = Field(default=None, max_length=50)

    address_line: str = Field(min_length=3, max_length=200)
    city: str = Field(min_length=2, max_length=120)
    county: str = Field(min_length=2, max_length=120)
    postal_code: str = Field(min_length=3, max_length=20)

    country: str = Field(default="RO", min_length=2, max_length=2)


class RegisterProviderRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=64)

    name: str = Field(min_length=2, max_length=120)
    provider_type: ProviderType = "clinic"

    website: Optional[str] = Field(default=None, max_length=500)
    image_url: Optional[str] = Field(default=None, max_length=1000)
    public_description: Optional[str] = Field(default=None, max_length=2000)

    specialty: Optional[str] = Field(default=None, max_length=500)
    services_offered: Optional[str] = Field(default=None, max_length=2000)

    cui: str = Field(min_length=2, max_length=50)
    trade_register_number: Optional[str] = Field(default=None, max_length=100)

    contact_person_name: str = Field(min_length=2, max_length=120)
    contact_email: EmailStr
    contact_phone: str = Field(min_length=3, max_length=50)

    phone: Optional[str] = Field(default=None, max_length=50)

    address_line: str = Field(min_length=3, max_length=200)
    city: str = Field(min_length=2, max_length=120)
    county: str = Field(min_length=2, max_length=120)
    postal_code: Optional[str] = Field(default=None, max_length=20)

    country: str = Field(default="RO", min_length=2, max_length=2)

    coverage_area: Optional[str] = Field(default=None, max_length=500)

    sanitary_authorization_number: str = Field(min_length=2, max_length=100)
    sanitary_authorization_expires_at: Optional[date] = None

    healthcare_compliance_confirmed: bool
    provider_agreement_accepted: bool