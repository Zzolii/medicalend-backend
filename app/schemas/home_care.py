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

        @router.get(
            "/providers/{provider_id}/staff",
            response_model=List[HomeCareStaffOut],
        )
        def list_home_care_provider_staff(
                provider_id: int,
                role: Optional[str] = Query(
                    "assistant",
                    description="Filter by clinic role. Defaults to assistant.",
                ),
                db: Session = Depends(get_db),
                current_user=Depends(get_current_user),
        ):
            provider = (
                db.query(models.Provider)
                .filter(
                    models.Provider.id == provider_id,
                    models.Provider.is_active == True,  # noqa: E712
                )
                .first()
            )

            if not provider:
                raise HTTPException(status_code=404, detail="Providerul nu a fost găsit.")

            clinic_id = getattr(provider, "clinic_id", None)
            if clinic_id is None:
                return []

            normalized_role = _normalize_clinic_role(role)

            query = (
                db.query(models.ClinicMembership, models.User)
                .join(models.User, models.User.id == models.ClinicMembership.user_id)
                .filter(
                    models.ClinicMembership.clinic_id == clinic_id,
                    models.ClinicMembership.is_active == True,  # noqa: E712
                    models.User.is_active == True,  # noqa: E712
                )
            )

            if normalized_role:
                query = query.filter(models.ClinicMembership.role == normalized_role)

            rows = query.order_by(models.User.email.asc()).all()

            return [
                HomeCareStaffOut(
                    membership_id=membership.id,
                    user_id=user.id,
                    clinic_id=membership.clinic_id,
                    role=_normalize_clinic_role(membership.role) or membership.role,
                    display_name=user.email.split("@")[0] if user.email else f"User #{user.id}",
                    email=user.email,
                )
                for membership, user in rows
            ]