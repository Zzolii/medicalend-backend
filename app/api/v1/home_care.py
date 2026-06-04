# Path: backend/app/api/v1/home_care.py

from datetime import datetime
from typing import List, Optional, Set

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import or_
from sqlalchemy.orm import Session

from app import models
from app.core.security import get_current_user
from app.core.subscription import ensure_clinic_has_active_subscription
from app.db import get_db
from app.schemas.home_care import (
    HomeCareCaseCreate,
    HomeCareCaseOut,
    HomeCareStaffOut,
    HomeCareCaseUpdate,
    HomeCareVisitCreate,
    HomeCareVisitOut,
    HomeCareVisitUpdate,
)

router = APIRouter(prefix="/home-care", tags=["home-care"])

CLINIC_ROLES = {"clinic_admin", "doctor", "assistant", "reception", "receptionist"}
HOME_CARE_WRITE_ROLES = {"clinic_admin", "doctor", "assistant", "reception", "receptionist"}


def _normalize_clinic_role(value: Optional[str]) -> Optional[str]:
    if value == "receptionist":
        return "reception"
    return value


def _raise_platform_admin_access_denied() -> None:
    raise HTTPException(
        status_code=403,
        detail="Administratorul platformei nu poate accesa direct date Home Care ale pacienților.",
    )


def _raise_not_allowed() -> None:
    raise HTTPException(status_code=403, detail="Nu ai acces la acest caz Home Care.")


def _get_my_patient_profile(db: Session, current_user):
    patient = (
        db.query(models.Patient)
        .filter(models.Patient.user_id == current_user.id)
        .first()
    )
    if not patient:
        raise HTTPException(
            status_code=404,
            detail="Profilul de pacient nu este asociat acestui cont.",
        )
    return patient


def _get_provider_for_user(db: Session, current_user) -> Optional[models.Provider]:
    if current_user.role == "admin":
        return None

    provider = (
        db.query(models.Provider)
        .filter(models.Provider.user_id == current_user.id)
        .first()
    )
    if not provider:
        return None

    if getattr(provider, "status", None) != "approved":
        raise HTTPException(status_code=403, detail="Profilul de furnizor nu este aprobat.")

    return provider


def _active_memberships(db: Session, current_user):
    return (
        db.query(models.ClinicMembership)
        .filter(
            models.ClinicMembership.user_id == current_user.id,
            models.ClinicMembership.is_active == True,  # noqa: E712
        )
        .all()
    )


def _clinic_ids_for_user(db: Session, current_user, *, write: bool = False) -> List[int]:
    memberships = _active_memberships(db, current_user)

    allowed_roles = HOME_CARE_WRITE_ROLES if write else CLINIC_ROLES
    clinic_ids: List[int] = []

    for membership in memberships:
        role = _normalize_clinic_role(getattr(membership, "role", None))
        clinic_id = getattr(membership, "clinic_id", None)

        if role in allowed_roles and clinic_id is not None and clinic_id not in clinic_ids:
            clinic_ids.append(clinic_id)

    return clinic_ids


def _patient_ids_from_clinic_activity(db: Session, clinic_ids: List[int]) -> Set[int]:
    if not clinic_ids:
        return set()

    provider_ids = [
        row[0]
        for row in db.query(models.Provider.id)
        .filter(models.Provider.clinic_id.in_(clinic_ids))
        .all()
    ]

    patient_ids: Set[int] = set()

    appointment_rows = (
        db.query(models.Appointment.patient_id)
        .filter(
            or_(
                models.Appointment.clinic_id.in_(clinic_ids),
                models.Appointment.provider_id.in_(provider_ids) if provider_ids else False,
            )
        )
        .all()
    )
    patient_ids.update(row[0] for row in appointment_rows if row[0] is not None)

    episode_rows = (
        db.query(models.CareEpisode.patient_id)
        .filter(
            models.CareEpisode.owner_provider_id.in_(provider_ids)
            if provider_ids
            else False
        )
        .all()
    )
    patient_ids.update(row[0] for row in episode_rows if row[0] is not None)

    return patient_ids


def _get_case_or_404(db: Session, case_id: int):
    case = (
        db.query(models.HomeCareCase)
        .filter(models.HomeCareCase.id == case_id)
        .first()
    )
    if not case:
        raise HTTPException(status_code=404, detail="Cazul Home Care nu a fost găsit.")
    return case


def _get_visit_or_404(db: Session, visit_id: int):
    visit = (
        db.query(models.HomeCareVisit)
        .filter(models.HomeCareVisit.id == visit_id)
        .first()
    )
    if not visit:
        raise HTTPException(status_code=404, detail="Vizita Home Care nu a fost găsită.")
    return visit


def _ensure_patient_exists(db: Session, patient_id: int):
    patient = db.query(models.Patient).filter(models.Patient.id == patient_id).first()
    if not patient:
        raise HTTPException(status_code=400, detail="Pacientul nu există.")
    return patient


def _ensure_clinic_access_for_case(
    db: Session,
    current_user,
    case,
    *,
    write: bool = False,
) -> None:
    if current_user.role == "admin":
        _raise_platform_admin_access_denied()

    if current_user.role == "patient":
        patient = _get_my_patient_profile(db, current_user)
        if case.patient_id != patient.id:
            _raise_not_allowed()
        if write:
            raise HTTPException(
                status_code=403,
                detail="Pacientul poate vizualiza, dar nu poate modifica vizitele Home Care.",
            )
        return

    clinic_ids = _clinic_ids_for_user(db, current_user, write=write)
    if case.clinic_id is not None and case.clinic_id in clinic_ids:
        return

    provider = _get_provider_for_user(db, current_user)
    if provider and case.owner_provider_id == provider.id:
        return

    _raise_not_allowed()


def _ensure_patient_visible_for_staff(
    db: Session,
    current_user,
    patient_id: int,
    clinic_id: Optional[int],
) -> None:
    if current_user.role == "admin":
        _raise_platform_admin_access_denied()

    if current_user.role == "patient":
        patient = _get_my_patient_profile(db, current_user)
        if patient.id != patient_id:
            _raise_not_allowed()
        raise HTTPException(
            status_code=403,
            detail="Pacientul nu poate crea cazuri Home Care.",
        )

    write_clinic_ids = _clinic_ids_for_user(db, current_user, write=True)
    provider = _get_provider_for_user(db, current_user)

    if clinic_id is not None:
        if clinic_id in write_clinic_ids:
            return

        if provider and getattr(provider, "clinic_id", None) == clinic_id:
            return

        raise HTTPException(status_code=403, detail="Nu poți crea caz Home Care pentru această clinică.")

    if provider:
        return

    if write_clinic_ids:
        return

    raise HTTPException(status_code=403, detail="Nu ai permisiunea de a crea caz Home Care.")


@router.post("/cases", response_model=HomeCareCaseOut, status_code=status.HTTP_201_CREATED)
def create_home_care_case(
    payload: HomeCareCaseCreate,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    patient = _ensure_patient_exists(db, payload.patient_id)

    clinic_id = payload.clinic_id
    owner_provider_id = payload.owner_provider_id

    provider = None
    if owner_provider_id is not None:
        provider = (
            db.query(models.Provider)
            .filter(models.Provider.id == owner_provider_id)
            .first()
        )
        if not provider:
            raise HTTPException(status_code=400, detail="Providerul nu există.")
        clinic_id = clinic_id or getattr(provider, "clinic_id", None)

    if clinic_id is None:
        user_provider = _get_provider_for_user(db, current_user)
        if user_provider:
            owner_provider_id = user_provider.id
            clinic_id = getattr(user_provider, "clinic_id", None)

    _ensure_patient_visible_for_staff(
        db,
        current_user,
        patient_id=patient.id,
        clinic_id=clinic_id,
    )

    if clinic_id:
        ensure_clinic_has_active_subscription(db, clinic_id)

    case = models.HomeCareCase(
        patient_id=patient.id,
        clinic_id=clinic_id,
        owner_provider_id=owner_provider_id,
        title=payload.title.strip(),
        status="active",
        address_line=payload.address_line,
        city=payload.city,
        county=payload.county,
        contact_phone=payload.contact_phone,
        care_plan=payload.care_plan,
        created_by_user_id=current_user.id,
    )

    db.add(case)
    db.commit()
    db.refresh(case)
    return case


@router.get("/cases", response_model=List[HomeCareCaseOut])
def list_home_care_cases(
    patient_id: Optional[int] = None,
    status_value: Optional[str] = Query(None, alias="status"),
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    if current_user.role == "admin":
        _raise_platform_admin_access_denied()

    query = db.query(models.HomeCareCase)

    if current_user.role == "patient":
        patient = _get_my_patient_profile(db, current_user)
        query = query.filter(models.HomeCareCase.patient_id == patient.id)
    else:
        clinic_ids = _clinic_ids_for_user(db, current_user)
        provider = _get_provider_for_user(db, current_user)

        filters = []
        if clinic_ids:
            filters.append(models.HomeCareCase.clinic_id.in_(clinic_ids))
        if provider:
            filters.append(models.HomeCareCase.owner_provider_id == provider.id)

        if not filters:
            _raise_not_allowed()

        query = query.filter(or_(*filters))

    if patient_id is not None:
        query = query.filter(models.HomeCareCase.patient_id == patient_id)

    if status_value:
        query = query.filter(models.HomeCareCase.status == status_value)

    return query.order_by(models.HomeCareCase.created_at.desc()).all()


@router.get("/cases/{case_id}", response_model=HomeCareCaseOut)
def get_home_care_case(
    case_id: int,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    case = _get_case_or_404(db, case_id)
    _ensure_clinic_access_for_case(db, current_user, case)
    return case


@router.put("/cases/{case_id}", response_model=HomeCareCaseOut)
def update_home_care_case(
    case_id: int,
    payload: HomeCareCaseUpdate,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    case = _get_case_or_404(db, case_id)
    _ensure_clinic_access_for_case(db, current_user, case, write=True)

    data = payload.model_dump(exclude_unset=True)

    if "title" in data and isinstance(data["title"], str):
        data["title"] = data["title"].strip()

    for key, value in data.items():
        setattr(case, key, value)

    db.commit()
    db.refresh(case)
    return case


@router.post("/visits", response_model=HomeCareVisitOut, status_code=status.HTTP_201_CREATED)
def create_home_care_visit(
    payload: HomeCareVisitCreate,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    case = _get_case_or_404(db, payload.case_id)
    _ensure_clinic_access_for_case(db, current_user, case, write=True)

    if case.clinic_id:
        ensure_clinic_has_active_subscription(db, case.clinic_id)

    visit = models.HomeCareVisit(
        case_id=case.id,
        patient_id=case.patient_id,
        clinic_id=case.clinic_id,
        scheduled_at=payload.scheduled_at,
        assigned_user_id=payload.assigned_user_id,
        status="scheduled",
        blood_pressure=payload.blood_pressure,
        blood_sugar=payload.blood_sugar,
        pulse=payload.pulse,
        temperature=payload.temperature,
        oxygen_saturation=payload.oxygen_saturation,
        note=payload.note,
        created_by_user_id=current_user.id,
    )

    db.add(visit)
    db.commit()
    db.refresh(visit)
    return visit


@router.get("/visits", response_model=List[HomeCareVisitOut])
def list_home_care_visits(
    case_id: Optional[int] = None,
    patient_id: Optional[int] = None,
    status_value: Optional[str] = Query(None, alias="status"),
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    if current_user.role == "admin":
        _raise_platform_admin_access_denied()

    query = db.query(models.HomeCareVisit)

    if current_user.role == "patient":
        patient = _get_my_patient_profile(db, current_user)
        query = query.filter(models.HomeCareVisit.patient_id == patient.id)
    else:
        clinic_ids = _clinic_ids_for_user(db, current_user)
        provider = _get_provider_for_user(db, current_user)

        filters = []
        if clinic_ids:
            filters.append(models.HomeCareVisit.clinic_id.in_(clinic_ids))
        if provider:
            owned_case_ids = (
                db.query(models.HomeCareCase.id)
                .filter(models.HomeCareCase.owner_provider_id == provider.id)
            )
            filters.append(models.HomeCareVisit.case_id.in_(owned_case_ids))

        if not filters:
            _raise_not_allowed()

        query = query.filter(or_(*filters))

    if case_id is not None:
        query = query.filter(models.HomeCareVisit.case_id == case_id)

    if patient_id is not None:
        query = query.filter(models.HomeCareVisit.patient_id == patient_id)

    if status_value:
        query = query.filter(models.HomeCareVisit.status == status_value)

    return query.order_by(models.HomeCareVisit.scheduled_at.desc()).all()


@router.get("/visits/{visit_id}", response_model=HomeCareVisitOut)
def get_home_care_visit(
    visit_id: int,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    visit = _get_visit_or_404(db, visit_id)
    case = _get_case_or_404(db, visit.case_id)
    _ensure_clinic_access_for_case(db, current_user, case)
    return visit


@router.put("/visits/{visit_id}", response_model=HomeCareVisitOut)
def update_home_care_visit(
    visit_id: int,
    payload: HomeCareVisitUpdate,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    visit = _get_visit_or_404(db, visit_id)
    case = _get_case_or_404(db, visit.case_id)
    _ensure_clinic_access_for_case(db, current_user, case, write=True)

    data = payload.model_dump(exclude_unset=True)

    if data.get("status") == "completed" and not data.get("completed_at") and not visit.completed_at:
        data["completed_at"] = datetime.now()

    for key, value in data.items():
        setattr(visit, key, value)

    db.commit()
    db.refresh(visit)
    return visit



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
        raise HTTPException(status_code=404, detail="Providerul nu a fost gasit.")

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

