# Path: backend/app/api/v1/provider_structure.py

from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app import models
from app.core.security import get_current_user
from app.db import get_db

from app.models.clinic_membership import ClinicMembership
from app.schemas.provider_structure import (
    ProviderDoctorCreate,
    ProviderDoctorExpandedOut,
    ProviderDoctorOut,
    ProviderDoctorUpdate,
    ProviderSpecialtyCreate,
    ProviderSpecialtyOut,
    ProviderSpecialtyUpdate,
    ProviderStructureOut,
)

router = APIRouter(prefix="/providers/me/structure", tags=["provider-structure"])

STAFF_MANAGE_ROLES = {
    "clinic_admin",
    "doctor",
    "assistant",
    "reception",
    "receptionist",
}


def _normalize_clinic_role(value: Optional[str]) -> Optional[str]:
    if value == "receptionist":
        return "reception"
    return value


def _get_active_staff_memberships(
    db: Session,
    current_user,
) -> List[ClinicMembership]:
    return (
        db.query(ClinicMembership)
        .filter(
            ClinicMembership.user_id == current_user.id,
            ClinicMembership.is_active == True,  # noqa: E712
        )
        .order_by(ClinicMembership.id.asc())
        .all()
    )


def _get_accessible_clinic_ids(db: Session, current_user) -> List[int]:
    memberships = _get_active_staff_memberships(db, current_user)

    clinic_ids: List[int] = []
    for membership in memberships:
        role = _normalize_clinic_role(getattr(membership, "role", None))
        clinic_id = getattr(membership, "clinic_id", None)

        if role in STAFF_MANAGE_ROLES and clinic_id is not None and clinic_id not in clinic_ids:
            clinic_ids.append(clinic_id)

    return clinic_ids


def _get_my_provider(db: Session, current_user) -> models.Provider:
    """
    Legacy owner-provider flow:
    a bejelentkezett provider saját provider profilját adja vissza.
    """
    if current_user.role not in ("provider", "admin"):
        raise HTTPException(status_code=403, detail="Not enough permissions")

    provider = (
        db.query(models.Provider)
        .filter(models.Provider.user_id == current_user.id)
        .first()
    )
    if not provider:
        raise HTTPException(
            status_code=404,
            detail="Provider profile not linked to this user",
        )

    return provider


def _get_provider_from_doctor_membership_context(
    db: Session,
    current_user,
) -> Optional[models.Provider]:
    """
    Ha a user doctor clinic membershippel rendelkezik és azon van provider_doctor_id,
    akkor abból a providerből dolgozunk. Ez a stabil és helyes orvos context.
    """
    memberships = _get_active_staff_memberships(db, current_user)

    for membership in memberships:
        role = _normalize_clinic_role(getattr(membership, "role", None))
        provider_doctor_id = getattr(membership, "provider_doctor_id", None)

        if role != "doctor" or provider_doctor_id is None:
            continue

        doctor = (
            db.query(models.ProviderDoctor)
            .filter(
                models.ProviderDoctor.id == provider_doctor_id,
                models.ProviderDoctor.is_active == True,  # noqa: E712
            )
            .first()
        )
        if not doctor:
            continue

        provider = (
            db.query(models.Provider)
            .filter(
                models.Provider.id == doctor.provider_id,
                models.Provider.is_active == True,  # noqa: E712
            )
            .first()
        )
        if provider:
            return provider

    return None


def _get_provider_from_staff_context(
    db: Session,
    current_user,
) -> Optional[models.Provider]:
    """
    Klinikás staff flow:
    1) ha doctor membershipből egyértelmű provider jön, azt használjuk
    2) különben a user klinikájához tartozó első aktív provider profilt használjuk
    """
    provider = _get_provider_from_doctor_membership_context(db, current_user)
    if provider:
        return provider

    clinic_ids = _get_accessible_clinic_ids(db, current_user)
    if not clinic_ids:
        return None

    provider = (
        db.query(models.Provider)
        .filter(
            models.Provider.clinic_id.in_(clinic_ids),
            models.Provider.is_active == True,  # noqa: E712
        )
        .order_by(models.Provider.id.asc())
        .first()
    )
    return provider


def _get_current_provider_context(db: Session, current_user) -> models.Provider:
    """
    Először próbáljuk a saját provider profilt.
    Ha nincs, de staff membership van, akkor a staff contextből jövő provider kell.
    Doctor usernél ez a doctor membershiphez kötött provider legyen.
    """
    if current_user.role == "admin":
        provider = _get_provider_from_staff_context(db, current_user)
        if provider:
            return provider
        raise HTTPException(status_code=404, detail="No provider found for admin context")

    if current_user.role == "provider":
        try:
            return _get_my_provider(db, current_user)
        except HTTPException:
            pass

    provider = _get_provider_from_staff_context(db, current_user)
    if provider:
        return provider

    raise HTTPException(status_code=403, detail="No provider context available")


def _sync_legacy_specialty_string(db: Session, provider_id: int) -> None:
    specialties = (
        db.query(models.ProviderSpecialty)
        .filter(
            models.ProviderSpecialty.provider_id == provider_id,
            models.ProviderSpecialty.is_active == True,  # noqa: E712
        )
        .order_by(models.ProviderSpecialty.name.asc())
        .all()
    )

    provider = db.query(models.Provider).filter(models.Provider.id == provider_id).first()
    if not provider:
        return

    provider.specialty = ", ".join([s.name for s in specialties]) if specialties else None
    db.commit()


def _doctor_row_to_out(
    doctor: models.ProviderDoctor,
    specialty_name: str,
) -> ProviderDoctorExpandedOut:
    return ProviderDoctorExpandedOut(
        id=doctor.id,
        provider_id=doctor.provider_id,
        specialty_id=doctor.specialty_id,
        name=doctor.name,
        title=doctor.title,
        license_number=doctor.license_number,
        phone=doctor.phone,
        email=doctor.email,
        is_active=doctor.is_active,
        created_at=doctor.created_at,
        specialty_name=specialty_name,
    )


@router.get("/", response_model=ProviderStructureOut)
def get_my_provider_structure(
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    provider = _get_current_provider_context(db, current_user)

    specialties = (
        db.query(models.ProviderSpecialty)
        .filter(models.ProviderSpecialty.provider_id == provider.id)
        .order_by(models.ProviderSpecialty.name.asc())
        .all()
    )

    doctors = (
        db.query(models.ProviderDoctor, models.ProviderSpecialty.name.label("specialty_name"))
        .join(models.ProviderSpecialty, models.ProviderDoctor.specialty_id == models.ProviderSpecialty.id)
        .filter(models.ProviderDoctor.provider_id == provider.id)
        .order_by(models.ProviderDoctor.name.asc())
        .all()
    )

    doctor_rows: List[ProviderDoctorExpandedOut] = [
        _doctor_row_to_out(doctor, specialty_name) for doctor, specialty_name in doctors
    ]

    return ProviderStructureOut(
        specialties=specialties,
        doctors=doctor_rows,
    )


@router.get("/specialties", response_model=List[ProviderSpecialtyOut])
def list_my_specialties(
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    provider = _get_current_provider_context(db, current_user)

    return (
        db.query(models.ProviderSpecialty)
        .filter(models.ProviderSpecialty.provider_id == provider.id)
        .order_by(models.ProviderSpecialty.name.asc())
        .all()
    )


@router.post("/specialties", response_model=ProviderSpecialtyOut, status_code=status.HTTP_201_CREATED)
def create_my_specialty(
    payload: ProviderSpecialtyCreate,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    provider = _get_current_provider_context(db, current_user)

    name = payload.name.strip()
    existing = (
        db.query(models.ProviderSpecialty)
        .filter(
            models.ProviderSpecialty.provider_id == provider.id,
            models.ProviderSpecialty.name.ilike(name),
        )
        .first()
    )
    if existing:
        raise HTTPException(status_code=409, detail="Specialty already exists")

    specialty = models.ProviderSpecialty(
        provider_id=provider.id,
        name=name,
        is_active=True,
    )
    db.add(specialty)
    db.commit()
    db.refresh(specialty)

    _sync_legacy_specialty_string(db, provider.id)
    db.refresh(specialty)
    return specialty


@router.put("/specialties/{specialty_id}", response_model=ProviderSpecialtyOut)
def update_my_specialty(
    specialty_id: int,
    payload: ProviderSpecialtyUpdate,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    provider = _get_current_provider_context(db, current_user)

    specialty = (
        db.query(models.ProviderSpecialty)
        .filter(
            models.ProviderSpecialty.id == specialty_id,
            models.ProviderSpecialty.provider_id == provider.id,
        )
        .first()
    )
    if not specialty:
        raise HTTPException(status_code=404, detail="Specialty not found")

    data = payload.model_dump(exclude_unset=True)

    if "name" in data and data["name"]:
        new_name = data["name"].strip()
        duplicate = (
            db.query(models.ProviderSpecialty)
            .filter(
                models.ProviderSpecialty.provider_id == provider.id,
                models.ProviderSpecialty.id != specialty.id,
                models.ProviderSpecialty.name.ilike(new_name),
            )
            .first()
        )
        if duplicate:
            raise HTTPException(
                status_code=409,
                detail="Another specialty already uses this name",
            )
        data["name"] = new_name

    for key, value in data.items():
        setattr(specialty, key, value)

    db.commit()
    db.refresh(specialty)

    _sync_legacy_specialty_string(db, provider.id)
    db.refresh(specialty)
    return specialty


@router.delete("/specialties/{specialty_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_my_specialty(
    specialty_id: int,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    provider = _get_current_provider_context(db, current_user)

    specialty = (
        db.query(models.ProviderSpecialty)
        .filter(
            models.ProviderSpecialty.id == specialty_id,
            models.ProviderSpecialty.provider_id == provider.id,
        )
        .first()
    )
    if not specialty:
        raise HTTPException(status_code=404, detail="Specialty not found")

    linked_doctor = (
        db.query(models.ProviderDoctor)
        .filter(
            models.ProviderDoctor.provider_id == provider.id,
            models.ProviderDoctor.specialty_id == specialty.id,
        )
        .first()
    )
    if linked_doctor:
        raise HTTPException(
            status_code=409,
            detail="Cannot delete specialty because it is used by one or more doctors",
        )

    db.delete(specialty)
    db.commit()

    _sync_legacy_specialty_string(db, provider.id)
    return None


@router.get("/doctors", response_model=List[ProviderDoctorExpandedOut])
def list_my_doctors(
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    provider = _get_current_provider_context(db, current_user)

    rows = (
        db.query(models.ProviderDoctor, models.ProviderSpecialty.name.label("specialty_name"))
        .join(models.ProviderSpecialty, models.ProviderDoctor.specialty_id == models.ProviderSpecialty.id)
        .filter(models.ProviderDoctor.provider_id == provider.id)
        .order_by(models.ProviderDoctor.name.asc())
        .all()
    )

    result: List[ProviderDoctorExpandedOut] = [
        _doctor_row_to_out(doctor, specialty_name) for doctor, specialty_name in rows
    ]
    return result


@router.post("/doctors", response_model=ProviderDoctorOut, status_code=status.HTTP_201_CREATED)
def create_my_doctor(
    payload: ProviderDoctorCreate,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    provider = _get_current_provider_context(db, current_user)

    specialty = (
        db.query(models.ProviderSpecialty)
        .filter(
            models.ProviderSpecialty.id == payload.specialty_id,
            models.ProviderSpecialty.provider_id == provider.id,
        )
        .first()
    )
    if not specialty:
        raise HTTPException(
            status_code=400,
            detail="Specialty does not belong to this provider",
        )

    name = payload.name.strip()
    existing = (
        db.query(models.ProviderDoctor)
        .filter(
            models.ProviderDoctor.provider_id == provider.id,
            models.ProviderDoctor.specialty_id == payload.specialty_id,
            models.ProviderDoctor.name.ilike(name),
        )
        .first()
    )
    if existing:
        raise HTTPException(
            status_code=409,
            detail="Doctor already exists in this specialty",
        )

    doctor = models.ProviderDoctor(
        provider_id=provider.id,
        specialty_id=payload.specialty_id,
        name=name,
        title=payload.title,
        license_number=payload.license_number,
        phone=payload.phone,
        email=payload.email,
        is_active=True,
    )
    db.add(doctor)
    db.commit()
    db.refresh(doctor)
    return doctor


@router.put("/doctors/{doctor_id}", response_model=ProviderDoctorOut)
def update_my_doctor(
    doctor_id: int,
    payload: ProviderDoctorUpdate,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    provider = _get_current_provider_context(db, current_user)

    doctor = (
        db.query(models.ProviderDoctor)
        .filter(
            models.ProviderDoctor.id == doctor_id,
            models.ProviderDoctor.provider_id == provider.id,
        )
        .first()
    )
    if not doctor:
        raise HTTPException(status_code=404, detail="Doctor not found")

    data = payload.model_dump(exclude_unset=True)

    next_specialty_id = data.get("specialty_id", doctor.specialty_id)
    specialty = (
        db.query(models.ProviderSpecialty)
        .filter(
            models.ProviderSpecialty.id == next_specialty_id,
            models.ProviderSpecialty.provider_id == provider.id,
        )
        .first()
    )
    if not specialty:
        raise HTTPException(
            status_code=400,
            detail="Specialty does not belong to this provider",
        )

    if "name" in data and data["name"]:
        data["name"] = data["name"].strip()

    check_name = data.get("name", doctor.name)
    duplicate = (
        db.query(models.ProviderDoctor)
        .filter(
            models.ProviderDoctor.provider_id == provider.id,
            models.ProviderDoctor.id != doctor.id,
            models.ProviderDoctor.specialty_id == next_specialty_id,
            models.ProviderDoctor.name.ilike(check_name),
        )
        .first()
    )
    if duplicate:
        raise HTTPException(
            status_code=409,
            detail="Another doctor already uses this name in this specialty",
        )

    for key, value in data.items():
        setattr(doctor, key, value)

    db.commit()
    db.refresh(doctor)
    return doctor


@router.delete("/doctors/{doctor_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_my_doctor(
    doctor_id: int,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    provider = _get_current_provider_context(db, current_user)

    doctor = (
        db.query(models.ProviderDoctor)
        .filter(
            models.ProviderDoctor.id == doctor_id,
            models.ProviderDoctor.provider_id == provider.id,
        )
        .first()
    )
    if not doctor:
        raise HTTPException(status_code=404, detail="Doctor not found")

    linked_membership = (
        db.query(models.ClinicMembership)
        .filter(
            models.ClinicMembership.provider_doctor_id == doctor.id,
            models.ClinicMembership.is_active == True,  # noqa: E712
        )
        .first()
    )
    if linked_membership:
        raise HTTPException(
            status_code=409,
            detail="Cannot delete doctor because it is linked to an active clinic staff user",
        )

    linked_appointment = (
        db.query(models.Appointment)
        .filter(models.Appointment.doctor_id == doctor.id)
        .first()
    )
    if linked_appointment:
        raise HTTPException(
            status_code=409,
            detail="Cannot delete doctor because it is already used in appointments",
        )

    db.delete(doctor)
    db.commit()
    return None