# Path: backend/app/schemas/admin.py

from datetime import datetime
from typing import Optional

from pydantic import BaseModel


class AdminProviderRow(BaseModel):
    id: int
    user_id: Optional[int] = None
    clinic_id: Optional[int] = None

    status: Optional[str] = None
    rejection_reason: Optional[str] = None

    provider_type: Optional[str] = None

    name: Optional[str] = None
    specialty: Optional[str] = None
    services_offered: Optional[str] = None
    license_number: Optional[str] = None

    cui: Optional[str] = None
    trade_register_number: Optional[str] = None

    contact_person_name: Optional[str] = None
    contact_email: Optional[str] = None
    contact_phone: Optional[str] = None

    phone: Optional[str] = None
    email: Optional[str] = None

    address_line: Optional[str] = None
    city: Optional[str] = None
    county: Optional[str] = None
    postal_code: Optional[str] = None
    country: Optional[str] = None

    coverage_area: Optional[str] = None

    sanitary_authorization_number: Optional[str] = None
    sanitary_authorization_expires_at: Optional[datetime] = None

    healthcare_compliance_confirmed: Optional[bool] = None
    provider_agreement_accepted: Optional[bool] = None

    is_active: Optional[bool] = None
    fhir_id: Optional[str] = None

    created_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class RejectProviderRequest(BaseModel):
    reason: str


class AdminReferralRow(BaseModel):
    id: int
    episode_id: int
    from_provider_id: Optional[int] = None
    to_provider_id: Optional[int] = None
    status: str
    reason: Optional[str] = None
    rejection_reason: Optional[str] = None
    created_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class AdminStatsOut(BaseModel):
    total_users: int
    total_patients: int
    total_providers: int

    pending_providers: int
    approved_providers: int
    rejected_providers: int

    total_clinics: int
    active_clinics: int

    total_referrals: int
    pending_referrals: int

    total_subscription_plans: int
    active_subscription_plans: int

    total_clinic_subscriptions: int
    active_subscriptions: int
    trialing_subscriptions: int
    expired_subscriptions: int
    canceled_subscriptions: int

    subscriptions_expiring_soon: int

    active_users_30d: int = 0
    new_patients_30d: int = 0
    appointments_7d: int = 0
    appointments_total: int = 0
    timeline_entries: int = 0
    documents_total: int = 0