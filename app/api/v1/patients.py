# Path: backend/app/api/v1/patients.py

from datetime import datetime
from typing import Any, Dict, List, Optional, Set

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app import models
from app.core.security import get_current_user, require_roles
from app.db import get_db
from app.models.appointment import Appointment as AppointmentModel
from app.models.care_episode import CareEpisode as CareEpisodeModel
from app.models.provider import Provider as ProviderModel
from app.schemas.patient import Patient, PatientCreate, PatientOut, PatientUpdate

router = APIRouter(
    prefix="/patients",
    tags=["patients"],
)

CLINIC_WIDE_ROLES = {"clinic_admin", "assistant", "reception", "receptionist"}
DOCTOR_ROLE = "doctor"
STAFF_VIEW_ROLES = CLINIC_WIDE_ROLES | {DOCTOR_ROLE}
REFERRAL_ACCESS_STATUSES = ("accepted", "in_progress", "completed", "pending")


class PatientDashboardNextAppointment(BaseModel):
    id: int
    start_time: datetime
    provider_name: Optional[str] = None
    status: str

    class Config:
        from_attributes = True


class PatientDashboardEpisode(BaseModel):
    id: int
    title: str
    status: str

    class Config:
        from_attributes = True


class PatientDashboardOut(BaseModel):
    next_appointment: Optional[PatientDashboardNextAppointment] = None
    active_episodes: List[PatientDashboardEpisode] = []


class PatientJourneyAppointmentOut(BaseModel):
    id: int
    provider_id: Optional[int] = None
    provider_name: Optional[str] = None
    doctor_id: Optional[int] = None
    start_time: datetime
    end_time: Optional[datetime] = None
    status: str
    notes: Optional[str] = None

    class Config:
        from_attributes = True


class PatientJourneyReferralOut(BaseModel):
    id: int
    from_provider_id: int
    from_provider_name: Optional[str] = None
    to_provider_id: int
    to_provider_name: Optional[str] = None
    reason: str
    status: str
    created_at: datetime

    class Config:
        from_attributes = True


class PatientJourneyEpisodeOut(BaseModel):
    id: int
    title: str
    status: str
    owner_provider_id: int
    owner_provider_name: Optional[str] = None
    created_at: datetime
    appointments: List[PatientJourneyAppointmentOut] = []
    referrals: List[PatientJourneyReferralOut] = []


class PatientJourneyOut(BaseModel):
    patient_id: int
    episodes: List[PatientJourneyEpisodeOut] = []


def _normalize_clinic_role(value: Optional[str]) -> Optional[str]:
    if value == "receptionist":
        return "reception"
    return value


def _raise_platform_admin_patient_access_denied() -> None:
    raise HTTPException(
        status_code=403,
        detail=(
            "Această zonă conține date medicale ale pacienților. "
            "Administratorul platformei poate vedea doar informații operaționale "
            "minime prin panoul de administrare."
        ),
    )


def _raise_access_denied() -> None:
    raise HTTPException(
        status_code=403,
        detail="Nu ai acces la datele acestui pacient.",
    )


def _raise_not_enough_permissions() -> None:
    raise HTTPException(
        status_code=403,
        detail="Nu ai permisiunea necesară pentru această secțiune.",
    )


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


def _try_get_my_provider_profile(db: Session, current_user) -> Optional[models.Provider]:
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
        raise HTTPException(
            status_code=403,
            detail="Profilul de furnizor nu este aprobat.",
        )

    return provider


def _build_staff_scope(db: Session, current_user) -> Dict[str, Any]:
    memberships = (
        db.query(models.ClinicMembership)
        .filter(
            models.ClinicMembership.user_id == current_user.id,
            models.ClinicMembership.is_active == True,  # noqa: E712
        )
        .all()
    )

    clinic_ids: Set[int] = set()
    clinic_wide_clinic_ids: Set[int] = set()
    doctor_ids: Set[int] = set()

    for membership in memberships:
        role = _normalize_clinic_role(getattr(membership, "role", None))
        clinic_id = getattr(membership, "clinic_id", None)

        if role not in STAFF_VIEW_ROLES or clinic_id is None:
            continue

        clinic_ids.add(clinic_id)

        if role in CLINIC_WIDE_ROLES:
            clinic_wide_clinic_ids.add(clinic_id)

        if role == DOCTOR_ROLE and getattr(membership, "provider_doctor_id", None):
            doctor_ids.add(membership.provider_doctor_id)

    return {
        "clinic_ids": list(clinic_ids),
        "clinic_wide_clinic_ids": list(clinic_wide_clinic_ids),
        "doctor_ids": list(doctor_ids),
    }


def _patient_ids_from_provider_scope_subquery(db: Session, provider_id: int):
    appointment_patients = (
        db.query(AppointmentModel.patient_id.label("patient_id"))
        .filter(AppointmentModel.provider_id == provider_id)
    )

    episode_patients = (
        db.query(CareEpisodeModel.patient_id.label("patient_id"))
        .filter(CareEpisodeModel.owner_provider_id == provider_id)
    )

    referral_episode_patients = (
        db.query(CareEpisodeModel.patient_id.label("patient_id"))
        .join(models.Referral, models.Referral.episode_id == CareEpisodeModel.id)
        .filter(
            models.Referral.status.in_(REFERRAL_ACCESS_STATUSES),
            or_(
                models.Referral.to_provider_id == provider_id,
                models.Referral.from_provider_id == provider_id,
            ),
        )
    )

    return appointment_patients.union(
        episode_patients,
        referral_episode_patients,
    ).subquery()


def _patient_ids_from_clinic_scope_subquery(db: Session, clinic_ids: List[int]):
    clinic_provider_ids = (
        db.query(ProviderModel.id.label("provider_id"))
        .filter(ProviderModel.clinic_id.in_(clinic_ids))
        .subquery()
    )

    appointment_patients = (
        db.query(AppointmentModel.patient_id.label("patient_id"))
        .filter(
            or_(
                AppointmentModel.clinic_id.in_(clinic_ids),
                AppointmentModel.provider_id.in_(
                    select(clinic_provider_ids.c.provider_id)
                ),
            )
        )
    )

    episode_patients = (
        db.query(CareEpisodeModel.patient_id.label("patient_id"))
        .filter(
            CareEpisodeModel.owner_provider_id.in_(
                select(clinic_provider_ids.c.provider_id)
            )
        )
    )

    referral_episode_patients = (
        db.query(CareEpisodeModel.patient_id.label("patient_id"))
        .join(models.Referral, models.Referral.episode_id == CareEpisodeModel.id)
        .filter(
            models.Referral.status.in_(REFERRAL_ACCESS_STATUSES),
            or_(
                models.Referral.to_provider_id.in_(
                    select(clinic_provider_ids.c.provider_id)
                ),
                models.Referral.from_provider_id.in_(
                    select(clinic_provider_ids.c.provider_id)
                ),
            ),
        )
    )

    return appointment_patients.union(
        episode_patients,
        referral_episode_patients,
    ).subquery()


def _patient_ids_from_doctor_scope_subquery(db: Session, doctor_ids: List[int]):
    return (
        db.query(AppointmentModel.patient_id.label("patient_id"))
        .filter(AppointmentModel.doctor_id.in_(doctor_ids))
        .subquery()
    )


def _build_patient_scope_filter(db: Session, current_user):
    if current_user.role == "admin":
        _raise_platform_admin_patient_access_denied()

    if current_user.role == "patient":
        patient = _get_my_patient_profile(db, current_user)
        return models.Patient.id == patient.id

    filters = []

    provider = _try_get_my_provider_profile(db, current_user)
    if provider:
        provider_patient_ids = _patient_ids_from_provider_scope_subquery(db, provider.id)
        filters.append(models.Patient.id.in_(select(provider_patient_ids.c.patient_id)))

    staff_scope = _build_staff_scope(db, current_user)

    if staff_scope["clinic_wide_clinic_ids"]:
        clinic_patient_ids = _patient_ids_from_clinic_scope_subquery(
            db,
            staff_scope["clinic_wide_clinic_ids"],
        )
        filters.append(models.Patient.id.in_(select(clinic_patient_ids.c.patient_id)))

    if staff_scope["doctor_ids"]:
        doctor_patient_ids = _patient_ids_from_doctor_scope_subquery(
            db,
            staff_scope["doctor_ids"],
        )
        filters.append(models.Patient.id.in_(select(doctor_patient_ids.c.patient_id)))

    if not filters:
        _raise_not_enough_permissions()

    return or_(*filters)


def _ensure_patient_access(db: Session, patient: models.Patient, current_user):
    if current_user.role == "admin":
        _raise_platform_admin_patient_access_denied()

    if current_user.role == "patient":
        own = _get_my_patient_profile(db, current_user)
        if own.id != patient.id:
            _raise_access_denied()
        return

    scope_filter = _build_patient_scope_filter(db, current_user)
    allowed = (
        db.query(models.Patient)
        .filter(models.Patient.id == patient.id)
        .filter(scope_filter)
        .first()
    )

    if not allowed:
        _raise_access_denied()


def _delete_patient_account_graph(db: Session, patient: models.Patient) -> None:
    patient_id = patient.id
    user_id = getattr(patient, "user_id", None)

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
                models.MedicalDocument.episode_id.in_(episode_ids)
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

    if user_id is not None:
        user = db.query(models.User).filter(models.User.id == user_id).first()
        if user:
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


@router.post(
    "/",
    response_model=Patient,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_roles("provider"))],
)
def create_patient(payload: PatientCreate, db: Session = Depends(get_db)):
    if payload.fhir_id:
        existing = (
            db.query(models.Patient)
            .filter(models.Patient.fhir_id == payload.fhir_id)
            .first()
        )
        if existing:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Există deja un pacient cu acest fhir_id.",
            )

    patient = models.Patient(**payload.model_dump())
    db.add(patient)
    db.commit()
    db.refresh(patient)
    return patient


@router.get("/", response_model=List[Patient])
def list_patients(
    skip: int = 0,
    limit: int = 50,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    query = db.query(models.Patient)

    scope_filter = _build_patient_scope_filter(db, current_user)
    query = query.filter(scope_filter)

    return query.offset(skip).limit(limit).all()


@router.get("/me", response_model=PatientOut)
def get_my_patient(
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    if current_user.role != "patient":
        _raise_not_enough_permissions()

    patient = _get_my_patient_profile(db, current_user)
    return patient


@router.put("/me", response_model=PatientOut)
def update_my_patient(
    payload: PatientUpdate,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    if current_user.role != "patient":
        raise HTTPException(
            status_code=403,
            detail="Doar conturile de pacient își pot actualiza profilul aici.",
        )

    patient = _get_my_patient_profile(db, current_user)
    data = payload.model_dump(exclude_unset=True)

    if "fhir_id" in data:
        data.pop("fhir_id", None)

    for key, value in data.items():
        setattr(patient, key, value)

    db.add(patient)
    db.commit()
    db.refresh(patient)

    return patient


@router.delete("/me", status_code=status.HTTP_200_OK)
def delete_my_patient_account(
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    if current_user.role != "patient":
        raise HTTPException(
            status_code=403,
            detail="Doar conturile de pacient își pot șterge profilul aici.",
        )

    patient = _get_my_patient_profile(db, current_user)
    patient_id = patient.id

    _delete_patient_account_graph(db, patient)
    db.commit()

    return {
        "ok": True,
        "patient_id": patient_id,
        "message": "Contul de pacient a fost șters definitiv.",
    }


@router.get("/me/dashboard", response_model=PatientDashboardOut)
def get_my_patient_dashboard(
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    if current_user.role != "patient":
        _raise_not_enough_permissions()

    patient = _get_my_patient_profile(db, current_user)

    now = datetime.now()

    next_appt = (
        db.query(AppointmentModel)
        .filter(
            AppointmentModel.patient_id == patient.id,
            AppointmentModel.start_time >= now,
            AppointmentModel.status != "canceled",
        )
        .order_by(AppointmentModel.start_time.asc())
        .first()
    )

    next_out: Optional[PatientDashboardNextAppointment] = None
    if next_appt:
        prov_name: Optional[str] = None
        if next_appt.provider_id:
            prov = (
                db.query(ProviderModel)
                .filter(ProviderModel.id == next_appt.provider_id)
                .first()
            )
            if prov:
                prov_name = getattr(prov, "name", None)

        next_out = PatientDashboardNextAppointment(
            id=next_appt.id,
            start_time=next_appt.start_time,
            provider_name=prov_name,
            status=next_appt.status,
        )

    active_eps = (
        db.query(CareEpisodeModel)
        .filter(
            CareEpisodeModel.patient_id == patient.id,
            CareEpisodeModel.status.notin_(["completed", "closed", "archived"]),
        )
        .order_by(CareEpisodeModel.created_at.desc())
        .limit(20)
        .all()
    )

    return PatientDashboardOut(
        next_appointment=next_out,
        active_episodes=[
            PatientDashboardEpisode(id=e.id, title=e.title, status=e.status)
            for e in active_eps
        ],
    )


@router.get("/search", response_model=List[Patient])
def search_patients(
    name: Optional[str] = None,
    city: Optional[str] = None,
    county: Optional[str] = None,
    phone: Optional[str] = None,
    email: Optional[str] = None,
    fhir_id: Optional[str] = None,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    query = db.query(models.Patient)

    scope_filter = _build_patient_scope_filter(db, current_user)
    query = query.filter(scope_filter)

    if fhir_id:
        query = query.filter(models.Patient.fhir_id == fhir_id)

    if city:
        query = query.filter(models.Patient.city.ilike(f"%{city}%"))

    if county:
        query = query.filter(models.Patient.county.ilike(f"%{county}%"))

    if phone:
        query = query.filter(models.Patient.phone.ilike(f"%{phone}%"))

    if email:
        query = query.filter(models.Patient.email.ilike(f"%{email}%"))

    if name:
        query = query.filter(
            or_(
                models.Patient.first_name.ilike(f"%{name}%"),
                models.Patient.last_name.ilike(f"%{name}%"),
            )
        )

    return query.all()


@router.get("/{patient_id}/journey", response_model=PatientJourneyOut)
def get_patient_journey(
    patient_id: int,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    patient = db.query(models.Patient).filter(models.Patient.id == patient_id).first()
    if not patient:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Pacientul nu a fost găsit.",
        )

    _ensure_patient_access(db, patient, current_user)

    episodes = (
        db.query(CareEpisodeModel)
        .filter(CareEpisodeModel.patient_id == patient.id)
        .order_by(CareEpisodeModel.created_at.desc(), CareEpisodeModel.id.desc())
        .all()
    )

    provider_ids: Set[int] = set()
    episode_ids: List[int] = []

    for episode in episodes:
        provider_ids.add(episode.owner_provider_id)
        episode_ids.append(episode.id)

    appointments_by_episode: Dict[int, List[AppointmentModel]] = {}
    referrals_by_episode: Dict[int, List[models.Referral]] = {}

    if episode_ids:
        appointments = (
            db.query(AppointmentModel)
            .filter(AppointmentModel.episode_id.in_(episode_ids))
            .order_by(AppointmentModel.start_time.desc(), AppointmentModel.id.desc())
            .all()
        )

        for appointment in appointments:
            if appointment.provider_id:
                provider_ids.add(appointment.provider_id)

            if appointment.episode_id is not None:
                appointments_by_episode.setdefault(
                    appointment.episode_id,
                    [],
                ).append(appointment)

        referrals = (
            db.query(models.Referral)
            .filter(models.Referral.episode_id.in_(episode_ids))
            .order_by(models.Referral.created_at.desc(), models.Referral.id.desc())
            .all()
        )

        for referral in referrals:
            provider_ids.add(referral.from_provider_id)
            provider_ids.add(referral.to_provider_id)
            referrals_by_episode.setdefault(referral.episode_id, []).append(referral)

    providers_by_id: Dict[int, ProviderModel] = {}
    if provider_ids:
        providers = (
            db.query(ProviderModel)
            .filter(ProviderModel.id.in_(list(provider_ids)))
            .all()
        )
        providers_by_id = {provider.id: provider for provider in providers}

    out_episodes: List[PatientJourneyEpisodeOut] = []

    for episode in episodes:
        owner_provider = providers_by_id.get(episode.owner_provider_id)

        episode_appointments: List[PatientJourneyAppointmentOut] = []
        for appointment in appointments_by_episode.get(episode.id, []):
            provider = (
                providers_by_id.get(appointment.provider_id)
                if appointment.provider_id
                else None
            )

            episode_appointments.append(
                PatientJourneyAppointmentOut(
                    id=appointment.id,
                    provider_id=appointment.provider_id,
                    provider_name=getattr(provider, "name", None) if provider else None,
                    doctor_id=getattr(appointment, "doctor_id", None),
                    start_time=appointment.start_time,
                    end_time=appointment.end_time,
                    status=appointment.status,
                    notes=appointment.notes,
                )
            )

        episode_referrals: List[PatientJourneyReferralOut] = []
        for referral in referrals_by_episode.get(episode.id, []):
            from_provider = providers_by_id.get(referral.from_provider_id)
            to_provider = providers_by_id.get(referral.to_provider_id)

            episode_referrals.append(
                PatientJourneyReferralOut(
                    id=referral.id,
                    from_provider_id=referral.from_provider_id,
                    from_provider_name=(
                        getattr(from_provider, "name", None)
                        if from_provider
                        else None
                    ),
                    to_provider_id=referral.to_provider_id,
                    to_provider_name=(
                        getattr(to_provider, "name", None)
                        if to_provider
                        else None
                    ),
                    reason=referral.reason,
                    status=referral.status,
                    created_at=referral.created_at,
                )
            )

        out_episodes.append(
            PatientJourneyEpisodeOut(
                id=episode.id,
                title=episode.title,
                status=episode.status,
                owner_provider_id=episode.owner_provider_id,
                owner_provider_name=(
                    getattr(owner_provider, "name", None) if owner_provider else None
                ),
                created_at=episode.created_at,
                appointments=episode_appointments,
                referrals=episode_referrals,
            )
        )

    return PatientJourneyOut(patient_id=patient.id, episodes=out_episodes)


@router.get("/{patient_id}", response_model=Patient)
def get_patient(
    patient_id: int,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    patient = db.query(models.Patient).filter(models.Patient.id == patient_id).first()
    if not patient:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Pacientul nu a fost găsit.",
        )

    _ensure_patient_access(db, patient, current_user)
    return patient


@router.put(
    "/{patient_id}",
    response_model=Patient,
    dependencies=[Depends(require_roles("provider"))],
)
def update_patient(
    patient_id: int,
    payload: PatientUpdate,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    patient = db.query(models.Patient).filter(models.Patient.id == patient_id).first()
    if not patient:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Pacientul nu a fost găsit.",
        )

    _ensure_patient_access(db, patient, current_user)

    data = payload.model_dump(exclude_unset=True)

    if "fhir_id" in data and data["fhir_id"]:
        existing = (
            db.query(models.Patient)
            .filter(
                models.Patient.fhir_id == data["fhir_id"],
                models.Patient.id != patient_id,
            )
            .first()
        )
        if existing:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Alt pacient folosește deja acest fhir_id.",
            )

    for key, value in data.items():
        setattr(patient, key, value)

    db.commit()
    db.refresh(patient)
    return patient


@router.delete(
    "/{patient_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(require_roles("provider"))],
)
def delete_patient(
    patient_id: int,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    patient = db.query(models.Patient).filter(models.Patient.id == patient_id).first()
    if not patient:
        raise HTTPException(status_code=404, detail="Pacientul nu a fost găsit.")

    _ensure_patient_access(db, patient, current_user)

    _delete_patient_account_graph(db, patient)
    db.commit()
    return None