# Path: backend/app/schemas/provider.py

from datetime import date, datetime
from typing import Literal, Optional

from pydantic import BaseModel, EmailStr


ProviderStatus = Literal["pending", "approved", "rejected"]
ProviderType = Literal["clinic", "home_care"]


class ProviderBase(BaseModel):
    name: str
    provider_type: ProviderType = "clinic"

    website: Optional[str] = None
    image_url: Optional[str] = None
    public_description: Optional[str] = None

    specialty: Optional[str] = None
    services_offered: Optional[str] = None
    license_number: Optional[str] = None

    cui: Optional[str] = None
    trade_register_number: Optional[str] = None

    contact_person_name: Optional[str] = None
    contact_email: Optional[EmailStr] = None
    contact_phone: Optional[str] = None

    phone: Optional[str] = None
    email: Optional[EmailStr] = None

    address_line: Optional[str] = None
    city: Optional[str] = None
    county: Optional[str] = None
    postal_code: Optional[str] = None
    country: Optional[str] = "RO"
    coverage_area: Optional[str] = None

    sanitary_authorization_number: Optional[str] = None
    sanitary_authorization_expires_at: Optional[date] = None

    healthcare_compliance_confirmed: bool = False
    provider_agreement_accepted: bool = False

    is_active: Optional[bool] = True
    fhir_id: Optional[str] = None

    user_id: Optional[int] = None
    clinic_id: Optional[int] = None

    status: Optional[ProviderStatus] = "pending"
    rejection_reason: Optional[str] = None


class ProviderCreate(ProviderBase):
    name: str


class ProviderUpdate(BaseModel):
    name: Optional[str] = None
    provider_type: Optional[ProviderType] = None

    website: Optional[str] = None
    image_url: Optional[str] = None
    public_description: Optional[str] = None

    specialty: Optional[str] = None
    services_offered: Optional[str] = None
    license_number: Optional[str] = None

    cui: Optional[str] = None
    trade_register_number: Optional[str] = None

    contact_person_name: Optional[str] = None
    contact_email: Optional[EmailStr] = None
    contact_phone: Optional[str] = None

    phone: Optional[str] = None
    email: Optional[EmailStr] = None

    address_line: Optional[str] = None
    city: Optional[str] = None
    county: Optional[str] = None
    postal_code: Optional[str] = None
    country: Optional[str] = None
    coverage_area: Optional[str] = None

    sanitary_authorization_number: Optional[str] = None
    sanitary_authorization_expires_at: Optional[date] = None

    healthcare_compliance_confirmed: Optional[bool] = None
    provider_agreement_accepted: Optional[bool] = None

    is_active: Optional[bool] = None
    fhir_id: Optional[str] = None

    user_id: Optional[int] = None
    clinic_id: Optional[int] = None

    status: Optional[ProviderStatus] = None
    rejection_reason: Optional[str] = None


class ProviderInDBBase(ProviderBase):
    id: int
    created_at: datetime

    class Config:
        from_attributes = True


class Provider(ProviderInDBBase):
    pass


class ProviderAvailabilitySlot(BaseModel):
    start_time: datetime
    end_time: datetime
    available: bool