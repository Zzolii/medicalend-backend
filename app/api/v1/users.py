# Path: backend/app/api/v1/users.py

from datetime import datetime, timezone
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func
from sqlalchemy.orm import Session, joinedload

from app import models
from app.core.security import (
    get_current_user,
    hash_password,
    require_roles,
)
from app.db import get_db
from app.models.provider import Provider as ProviderModel
from app.models.provider_doctor import ProviderDoctor as ProviderDoctorModel
from app.models.user import User
from app.schemas.user import (
    ClinicStaffCreate,
    ClinicStaffRow,
    ClinicStaffUpdate,
    User as UserOut,
    UserCreate,
    UserUpdate,
    UserWithMemberships,
)

router = APIRouter(prefix="/users", tags=["users"])

ALLOWED_CLINIC_STAFF_ROLES = {
    "clinic_admin",
    "doctor",
    "assistant",
    "reception",
}


def _normalize_email(value: str) -> str:
    return (value or "").strip().lower()


def _normalize_clinic_role(value: Optional[str]) -> Optional[str]:
    if value == "receptionist":
        return "reception"
    return value


def _get_my_active_clinic_admin_membership(
    db: Session,
    current_user,
) -> models.ClinicMembership:
    membership = (
        db.query(models.ClinicMembership)
        .filter(
            models.ClinicMembership.user_id == current_user.id,
            models.ClinicMembership.is_active == True,  # noqa: E712
            models.ClinicMembership.role == "clinic_admin",
        )
        .first()
    )
    if not membership:
        raise HTTPException(
            status_code=403,
            detail="Clinic admin membership required",
        )
    return membership


def _delete_patient_account_graph_for_user(db: Session, user: models.User) -> bool:
    patient = (
        db.query(models.Patient)
        .filter(models.Patient.user_id == user.id)
        .first()
    )

    if not patient:
        return False

    patient_id = patient.id

    episode_ids = [
        row[0]
        for row in db.query(models.CareEpisode.id)
        .filter(models.CareEpisode.patient_id == patient_id)
        .all()
    ]

    appointment_ids = [
        row[0]
        for row in db.query(models.Appointment.id)
        .filter(models.Appointment.patient_id == patient_id)
        .all()
    ]

    if appointment_ids:
        db.query(models.CareTask).filter(
            models.CareTask.appointment_id.in_(appointment_ids)
        ).delete(synchronize_session=False)

    if episode_ids:
        db.query(models.CareTask).filter(
            models.CareTask.episode_id.in_(episode_ids)
        ).delete(synchronize_session=False)

        db.query(models.CareNote).filter(
            models.CareNote.episode_id.in_(episode_ids)
        ).delete(synchronize_session=False)

        db.query(models.Referral).filter(
            models.Referral.episode_id.in_(episode_ids)
        ).delete(synchronize_session=False)

    if hasattr(models, "MedicalDocument"):
        db.query(models.MedicalDocument).filter(
            models.MedicalDocument.patient_id == patient_id
        ).delete(synchronize_session=False)

    db.query(models.Appointment).filter(
        models.Appointment.patient_id == patient_id
    ).delete(synchronize_session=False)

    if episode_ids:
        db.query(models.CareEpisode).filter(
            models.CareEpisode.id.in_(episode_ids)
        ).delete(synchronize_session=False)

    db.delete(patient)
    db.flush()

    db.query(models.Appointment).filter(
        models.Appointment.created_by_user_id == user.id
    ).update(
        {models.Appointment.created_by_user_id: None},
        synchronize_session=False,
    )

    db.query(models.ClinicMembership).filter(
        models.ClinicMembership.user_id == user.id
    ).delete(synchronize_session=False)

    db.delete(user)
    db.flush()
    return True


def _delete_non_patient_user_if_safe(db: Session, user: models.User) -> None:
    db.query(models.Appointment).filter(
        models.Appointment.created_by_user_id == user.id
    ).update(
        {models.Appointment.created_by_user_id: None},
        synchronize_session=False,
    )

    db.query(models.ClinicMembership).filter(
        models.ClinicMembership.user_id == user.id
    ).delete(synchronize_session=False)

    db.delete(user)
    db.flush()


def _get_provider_doctor_for_clinic(
    db: Session,
    *,
    clinic_id: int,
    provider_doctor_id: Optional[int],
) -> Optional[ProviderDoctorModel]:
    if provider_doctor_id is None:
        return None

    doctor = (
        db.query(ProviderDoctorModel)
        .join(ProviderModel, ProviderDoctorModel.provider_id == ProviderModel.id)
        .filter(
            ProviderDoctorModel.id == provider_doctor_id,
            ProviderDoctorModel.is_active == True,  # noqa: E712
            ProviderModel.clinic_id == clinic_id,
            ProviderModel.is_active == True,  # noqa: E712
        )
        .first()
    )
    return doctor


def _ensure_doctor_profile_not_already_linked(
    db: Session,
    *,
    clinic_id: int,
    provider_doctor_id: Optional[int],
    exclude_user_id: Optional[int] = None,
) -> None:
    if provider_doctor_id is None:
        return

    query = (
        db.query(models.ClinicMembership)
        .filter(
            models.ClinicMembership.clinic_id == clinic_id,
            models.ClinicMembership.provider_doctor_id == provider_doctor_id,
            models.ClinicMembership.is_active == True,  # noqa: E712
        )
    )

    if exclude_user_id is not None:
        query = query.filter(models.ClinicMembership.user_id != exclude_user_id)

    existing = query.first()
    if existing:
        raise HTTPException(
            status_code=409,
            detail="This doctor profile is already linked to another active user",
        )


def _validate_staff_role_and_doctor_link(
    db: Session,
    *,
    clinic_id: int,
    clinic_role: str,
    provider_doctor_id: Optional[int],
    exclude_user_id: Optional[int] = None,
) -> Optional[ProviderDoctorModel]:
    clinic_role = _normalize_clinic_role(clinic_role)

    if clinic_role not in ALLOWED_CLINIC_STAFF_ROLES:
        raise HTTPException(status_code=400, detail="Invalid clinic role")

    doctor = _get_provider_doctor_for_clinic(
        db,
        clinic_id=clinic_id,
        provider_doctor_id=provider_doctor_id,
    )

    if clinic_role == "doctor":
        if provider_doctor_id is None:
            raise HTTPException(
                status_code=400,
                detail="Doctor role requires provider_doctor_id",
            )

        if not doctor:
            raise HTTPException(
                status_code=400,
                detail="Doctor record not found in this clinic",
            )

        _ensure_doctor_profile_not_already_linked(
            db,
            clinic_id=clinic_id,
            provider_doctor_id=provider_doctor_id,
            exclude_user_id=exclude_user_id,
        )
        return doctor

    if provider_doctor_id is not None:
        raise HTTPException(
            status_code=400,
            detail="provider_doctor_id is allowed only for doctor role",
        )

    return None


def _serialize_staff_row(
    user: models.User,
    membership: models.ClinicMembership,
) -> dict:
    doctor = getattr(membership, "provider_doctor", None)

    doctor_name = None
    if doctor:
        title = getattr(doctor, "title", None) or ""
        name = getattr(doctor, "name", None) or ""
        doctor_name = f"{title} {name}".strip() or None

    return {
        "user_id": user.id,
        "email": user.email,
        "global_role": user.role,
        "user_is_active": user.is_active,
        "membership_id": membership.id,
        "clinic_id": membership.clinic_id,
        "clinic_role": membership.role,
        "provider_doctor_id": membership.provider_doctor_id,
        "provider_doctor_name": doctor_name,
        "membership_is_active": membership.is_active,
        "created_at": user.created_at,
    }


@router.get(
    "/",
    response_model=List[UserOut],
    dependencies=[Depends(require_roles("admin"))],
)
def list_users(db: Session = Depends(get_db)):
    return db.query(User).all()


@router.get("/me", response_model=UserWithMemberships)
def read_me(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    user = (
        db.query(User)
        .options(
            joinedload(User.clinic_memberships).joinedload(
                models.ClinicMembership.provider_doctor
            )
        )
        .filter(User.id == current_user.id)
        .first()
    )
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    return user


@router.get(
    "/{user_id}",
    response_model=UserOut,
    dependencies=[Depends(require_roles("admin"))],
)
def get_user(user_id: int, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    return user


@router.post(
    "/",
    response_model=UserOut,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_roles("admin"))],
)
def create_user(payload: UserCreate, db: Session = Depends(get_db)):
    normalized_email = _normalize_email(payload.email)

    existing = db.query(User).filter(func.lower(User.email) == normalized_email).first()
    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Email already registered",
        )

    user = User(
        email=normalized_email,
        hashed_password=hash_password(payload.password),
        role="provider",
        is_active=True,
    )

    db.add(user)
    db.commit()
    db.refresh(user)
    return user


@router.put(
    "/{user_id}",
    response_model=UserOut,
    dependencies=[Depends(require_roles("admin"))],
)
def update_user(user_id: int, payload: UserUpdate, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    update_data = payload.model_dump(exclude_unset=True)

    if "email" in update_data and update_data["email"]:
        normalized_email = _normalize_email(update_data["email"])
        duplicate = (
            db.query(User)
            .filter(func.lower(User.email) == normalized_email, User.id != user.id)
            .first()
        )
        if duplicate:
            raise HTTPException(status_code=409, detail="Email already registered")
        update_data["email"] = normalized_email

    if "password" in update_data and update_data["password"]:
        update_data["hashed_password"] = hash_password(update_data.pop("password"))
    else:
        update_data.pop("password", None)

    for field, value in update_data.items():
        setattr(user, field, value)

    db.commit()
    db.refresh(user)
    return user


@router.delete(
    "/{user_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(require_roles("admin"))],
)
def delete_user(user_id: int, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    if not _delete_patient_account_graph_for_user(db, user):
        _delete_non_patient_user_if_safe(db, user)

    db.commit()
    return None


@router.get("/clinic/staff", response_model=List[ClinicStaffRow])
def list_my_clinic_staff(
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    if current_user.role == "admin":
        memberships = (
            db.query(models.ClinicMembership)
            .options(joinedload(models.ClinicMembership.provider_doctor))
            .order_by(models.ClinicMembership.id.asc())
            .all()
        )
    else:
        admin_membership = _get_my_active_clinic_admin_membership(db, current_user)
        memberships = (
            db.query(models.ClinicMembership)
            .options(joinedload(models.ClinicMembership.provider_doctor))
            .filter(models.ClinicMembership.clinic_id == admin_membership.clinic_id)
            .order_by(models.ClinicMembership.id.asc())
            .all()
        )

    rows: List[dict] = []
    for membership in memberships:
        user = db.query(models.User).filter(models.User.id == membership.user_id).first()
        if not user:
            continue
        rows.append(_serialize_staff_row(user, membership))

    return rows


@router.post(
    "/clinic/staff",
    response_model=ClinicStaffRow,
    status_code=status.HTTP_201_CREATED,
)
def create_my_clinic_staff(
    payload: ClinicStaffCreate,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    if current_user.role == "admin":
        raise HTTPException(
            status_code=400,
            detail="Admin should use clinic-specific flows, not this endpoint directly",
        )

    admin_membership = _get_my_active_clinic_admin_membership(db, current_user)

    clinic_role = _normalize_clinic_role(payload.clinic_role)
    doctor = _validate_staff_role_and_doctor_link(
        db,
        clinic_id=admin_membership.clinic_id,
        clinic_role=clinic_role,
        provider_doctor_id=payload.provider_doctor_id,
        exclude_user_id=None,
    )

    normalized_email = _normalize_email(payload.email)

    existing = (
        db.query(models.User)
        .filter(func.lower(models.User.email) == normalized_email)
        .first()
    )
    if existing:
        raise HTTPException(status_code=409, detail="Email already registered")

    user = models.User(
        email=normalized_email,
        hashed_password=hash_password(payload.password),
        role="provider",
        is_active=payload.is_active,
        is_email_verified=True,
        email_verified_at=datetime.now(timezone.utc),
    )
    db.add(user)
    db.flush()

    membership = models.ClinicMembership(
        user_id=user.id,
        clinic_id=admin_membership.clinic_id,
        role=clinic_role,
        provider_doctor_id=doctor.id if doctor else None,
        is_active=payload.is_active,
    )
    db.add(membership)
    db.commit()

    db.refresh(user)
    membership = (
        db.query(models.ClinicMembership)
        .options(joinedload(models.ClinicMembership.provider_doctor))
        .filter(models.ClinicMembership.id == membership.id)
        .first()
    )
    return _serialize_staff_row(user, membership)


@router.put("/clinic/staff/{user_id}", response_model=ClinicStaffRow)
def update_my_clinic_staff(
    user_id: int,
    payload: ClinicStaffUpdate,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    if current_user.role == "admin":
        raise HTTPException(
            status_code=400,
            detail="Admin should use clinic-specific flows, not this endpoint directly",
        )

    admin_membership = _get_my_active_clinic_admin_membership(db, current_user)

    membership = (
        db.query(models.ClinicMembership)
        .options(joinedload(models.ClinicMembership.provider_doctor))
        .filter(
            models.ClinicMembership.user_id == user_id,
            models.ClinicMembership.clinic_id == admin_membership.clinic_id,
        )
        .first()
    )
    if not membership:
        raise HTTPException(status_code=404, detail="Clinic staff member not found")

    user = db.query(models.User).filter(models.User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    data = payload.model_dump(exclude_unset=True)

    current_membership_role = _normalize_clinic_role(membership.role)
    next_role = _normalize_clinic_role(data.get("clinic_role", current_membership_role))
    next_provider_doctor_id = data.get(
        "provider_doctor_id",
        membership.provider_doctor_id,
    )

    doctor = _validate_staff_role_and_doctor_link(
        db,
        clinic_id=admin_membership.clinic_id,
        clinic_role=next_role,
        provider_doctor_id=next_provider_doctor_id,
        exclude_user_id=user_id,
    )

    if "email" in data and data["email"]:
        normalized_email = _normalize_email(data["email"])
        duplicate = (
            db.query(models.User)
            .filter(func.lower(models.User.email) == normalized_email, models.User.id != user.id)
            .first()
        )
        if duplicate:
            raise HTTPException(status_code=409, detail="Email already registered")
        user.email = normalized_email

    if "clinic_role" in data and data["clinic_role"]:
        membership.role = next_role

    if "provider_doctor_id" in data or next_role != current_membership_role:
        membership.provider_doctor_id = doctor.id if doctor else None

    if "is_active" in data and data["is_active"] is not None:
        membership.is_active = data["is_active"]
        user.is_active = data["is_active"]

    if "password" in data and data["password"]:
        user.hashed_password = hash_password(data["password"])

    db.commit()
    db.refresh(user)

    membership = (
        db.query(models.ClinicMembership)
        .options(joinedload(models.ClinicMembership.provider_doctor))
        .filter(models.ClinicMembership.id == membership.id)
        .first()
    )

    return _serialize_staff_row(user, membership)


@router.delete("/clinic/staff/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_my_clinic_staff(
    user_id: int,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    if current_user.role == "admin":
        raise HTTPException(
            status_code=400,
            detail="Admin should use clinic-specific flows, not this endpoint directly",
        )

    admin_membership = _get_my_active_clinic_admin_membership(db, current_user)

    membership = (
        db.query(models.ClinicMembership)
        .filter(
            models.ClinicMembership.user_id == user_id,
            models.ClinicMembership.clinic_id == admin_membership.clinic_id,
        )
        .first()
    )
    if not membership:
        raise HTTPException(status_code=404, detail="Clinic staff member not found")

    user = db.query(models.User).filter(models.User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    if user.id == current_user.id:
        raise HTTPException(
            status_code=409,
            detail="Clinic admin cannot delete self from clinic",
        )

    db.delete(membership)
    db.flush()

    remaining_membership = (
        db.query(models.ClinicMembership)
        .filter(models.ClinicMembership.user_id == user.id)
        .first()
    )

    if not remaining_membership:
        if not _delete_patient_account_graph_for_user(db, user):
            _delete_non_patient_user_if_safe(db, user)

    db.commit()
    return None