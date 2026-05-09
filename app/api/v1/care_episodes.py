# Path: backend/app/api/v1/care_episodes.py

from typing import Any, Dict, List, Optional, Set

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.encoders import jsonable_encoder
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app import models
from app.core.security import get_current_user
from app.db import get_db
from app.schemas.care_episode import (
    CareEpisodeCreate,
    CareEpisodeOut,
    CareEpisodeUpdate,
)
from app.schemas.care_note import CareNoteCreate, CareNoteOut
from app.schemas.care_task import CareTaskCreate, CareTaskOut, CareTaskUpdate

router = APIRouter(prefix="/care-episodes", tags=["care-episodes"])

REFERRAL_ACCESS_STATUSES = ("accepted", "in_progress", "completed", "pending")
CLINIC_WIDE_ROLES = {"clinic_admin", "assistant", "reception", "receptionist"}
DOCTOR_ROLE = "doctor"
STAFF_VIEW_ROLES = CLINIC_WIDE_ROLES | {DOCTOR_ROLE}


def _normalize_clinic_role(value: Optional[str]) -> Optional[str]:
    if value == "receptionist":
        return "reception"
    return value


def _raise_platform_admin_medical_access_denied() -> None:
    raise HTTPException(
        status_code=403,
        detail=(
            "Administratorul platformei nu poate accesa direct date medicale, "
            "journey-uri sau timeline-uri ale pacienților."
        ),
    )


def _raise_not_enough_permissions() -> None:
    raise HTTPException(
        status_code=403,
        detail="Nu ai permisiunea necesară pentru această secțiune.",
    )


def _raise_access_denied() -> None:
    raise HTTPException(
        status_code=403,
        detail="Nu ai acces la acest episod medical.",
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


def _try_get_my_provider_profile(
    db: Session, current_user
) -> Optional[models.Provider]:
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


def _get_episode_or_404(db: Session, episode_id: int) -> models.CareEpisode:
    ep = (
        db.query(models.CareEpisode)
        .filter(models.CareEpisode.id == episode_id)
        .first()
    )
    if not ep:
        raise HTTPException(status_code=404, detail="Episodul medical nu a fost găsit.")
    return ep


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
    clinic_roles: Set[str] = set()

    for membership in memberships:
        role = _normalize_clinic_role(getattr(membership, "role", None))
        clinic_id = getattr(membership, "clinic_id", None)

        if role:
            clinic_roles.add(role)

        if role not in STAFF_VIEW_ROLES or clinic_id is None:
            continue

        clinic_ids.add(clinic_id)

        if role in CLINIC_WIDE_ROLES:
            clinic_wide_clinic_ids.add(clinic_id)

        provider_doctor_id = getattr(membership, "provider_doctor_id", None)
        if role == DOCTOR_ROLE and provider_doctor_id:
            doctor_ids.add(provider_doctor_id)

    return {
        "clinic_ids": list(clinic_ids),
        "clinic_wide_clinic_ids": list(clinic_wide_clinic_ids),
        "doctor_ids": list(doctor_ids),
        "clinic_roles": list(clinic_roles),
    }


def _episode_ids_from_provider_referrals_subquery(db: Session, provider_id: int):
    return (
        db.query(models.Referral.episode_id.label("episode_id"))
        .filter(
            models.Referral.status.in_(REFERRAL_ACCESS_STATUSES),
            or_(
                models.Referral.to_provider_id == provider_id,
                models.Referral.from_provider_id == provider_id,
            ),
        )
        .subquery()
    )


def _episode_ids_from_clinic_referrals_subquery(
    db: Session, clinic_ids: List[int]
):
    clinic_provider_ids = (
        db.query(models.Provider.id.label("provider_id"))
        .filter(models.Provider.clinic_id.in_(clinic_ids))
        .subquery()
    )

    return (
        db.query(models.Referral.episode_id.label("episode_id"))
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
        .subquery()
    )


def _episode_ids_from_clinic_appointments_subquery(
    db: Session, clinic_ids: List[int]
):
    clinic_provider_ids = (
        db.query(models.Provider.id.label("provider_id"))
        .filter(models.Provider.clinic_id.in_(clinic_ids))
        .subquery()
    )

    return (
        db.query(models.Appointment.episode_id.label("episode_id"))
        .filter(models.Appointment.episode_id.isnot(None))
        .filter(
            or_(
                models.Appointment.clinic_id.in_(clinic_ids),
                models.Appointment.provider_id.in_(
                    select(clinic_provider_ids.c.provider_id)
                ),
            )
        )
        .subquery()
    )


def _episode_ids_from_doctor_appointments_subquery(
    db: Session, doctor_ids: List[int]
):
    return (
        db.query(models.Appointment.episode_id.label("episode_id"))
        .filter(
            models.Appointment.episode_id.isnot(None),
            models.Appointment.doctor_id.in_(doctor_ids),
        )
        .subquery()
    )


def _provider_can_access_episode(
    db: Session, episode: models.CareEpisode, provider_id: int
) -> bool:
    if episode.owner_provider_id == provider_id:
        return True

    exists = (
        db.query(models.Referral)
        .filter(models.Referral.episode_id == episode.id)
        .filter(
            models.Referral.status.in_(REFERRAL_ACCESS_STATUSES),
            or_(
                models.Referral.to_provider_id == provider_id,
                models.Referral.from_provider_id == provider_id,
            ),
        )
        .first()
    )
    if exists:
        return True

    appointment_exists = (
        db.query(models.Appointment)
        .filter(
            models.Appointment.episode_id == episode.id,
            models.Appointment.provider_id == provider_id,
        )
        .first()
    )
    return appointment_exists is not None


def _clinic_staff_can_access_episode(
    db: Session,
    episode: models.CareEpisode,
    *,
    clinic_wide_clinic_ids: List[int],
    doctor_ids: List[int],
) -> bool:
    if clinic_wide_clinic_ids:
        owner_provider = (
            db.query(models.Provider)
            .filter(models.Provider.id == episode.owner_provider_id)
            .first()
        )
        if (
            owner_provider
            and getattr(owner_provider, "clinic_id", None)
            in clinic_wide_clinic_ids
        ):
            return True

        clinic_provider_ids = (
            db.query(models.Provider.id.label("provider_id"))
            .filter(models.Provider.clinic_id.in_(clinic_wide_clinic_ids))
            .subquery()
        )

        clinic_referral = (
            db.query(models.Referral)
            .filter(
                models.Referral.episode_id == episode.id,
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
            .first()
        )
        if clinic_referral:
            return True

        clinic_appointment = (
            db.query(models.Appointment)
            .filter(
                models.Appointment.episode_id == episode.id,
                or_(
                    models.Appointment.clinic_id.in_(clinic_wide_clinic_ids),
                    models.Appointment.provider_id.in_(
                        select(clinic_provider_ids.c.provider_id)
                    ),
                ),
            )
            .first()
        )
        if clinic_appointment:
            return True

    if doctor_ids:
        doctor_appointment = (
            db.query(models.Appointment)
            .filter(
                models.Appointment.episode_id == episode.id,
                models.Appointment.doctor_id.in_(doctor_ids),
            )
            .first()
        )
        if doctor_appointment:
            return True

    return False


def _ensure_episode_access(db: Session, episode: models.CareEpisode, current_user):
    if current_user.role == "admin":
        _raise_platform_admin_medical_access_denied()

    if current_user.role == "patient":
        patient = _get_my_patient_profile(db, current_user)
        if episode.patient_id != patient.id:
            _raise_access_denied()
        return

    staff_scope = _build_staff_scope(db, current_user)
    if _clinic_staff_can_access_episode(
        db,
        episode,
        clinic_wide_clinic_ids=staff_scope["clinic_wide_clinic_ids"],
        doctor_ids=staff_scope["doctor_ids"],
    ):
        return

    provider = _try_get_my_provider_profile(db, current_user)
    if provider and _provider_can_access_episode(db, episode, provider.id):
        return

    _raise_not_enough_permissions()


def _ensure_episode_write_access(
    db: Session, episode: models.CareEpisode, current_user
):
    if current_user.role == "admin":
        _raise_platform_admin_medical_access_denied()

    if current_user.role == "patient":
        raise HTTPException(
            status_code=403,
            detail="Pacienții nu pot modifica episoade medicale.",
        )

    _ensure_episode_access(db, episode, current_user)


@router.post("/", response_model=CareEpisodeOut, status_code=status.HTTP_201_CREATED)
def create_episode(
    payload: CareEpisodeCreate,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    if current_user.role == "admin":
        _raise_platform_admin_medical_access_denied()

    if current_user.role != "provider":
        _raise_not_enough_permissions()

    patient = (
        db.query(models.Patient)
        .filter(models.Patient.id == payload.patient_id)
        .first()
    )
    if not patient:
        raise HTTPException(status_code=400, detail="Pacientul nu există.")

    provider = _try_get_my_provider_profile(db, current_user)
    if not provider:
        raise HTTPException(
            status_code=403,
            detail="Profilul de furnizor nu este asociat acestui cont.",
        )

    episode = models.CareEpisode(
        patient_id=payload.patient_id,
        owner_provider_id=provider.id,
        title=payload.title,
        status="open",
    )
    db.add(episode)
    db.commit()
    db.refresh(episode)
    return episode


@router.get("/", response_model=List[CareEpisodeOut])
def list_episodes(
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    if current_user.role == "admin":
        _raise_platform_admin_medical_access_denied()

    if current_user.role == "patient":
        patient = _get_my_patient_profile(db, current_user)
        return (
            db.query(models.CareEpisode)
            .filter(models.CareEpisode.patient_id == patient.id)
            .order_by(models.CareEpisode.id.desc())
            .all()
        )

    filters = []

    provider = _try_get_my_provider_profile(db, current_user)
    if provider:
        provider_referral_episode_ids = _episode_ids_from_provider_referrals_subquery(
            db, provider.id
        )
        filters.append(models.CareEpisode.owner_provider_id == provider.id)
        filters.append(
            models.CareEpisode.id.in_(
                select(provider_referral_episode_ids.c.episode_id)
            )
        )

    staff_scope = _build_staff_scope(db, current_user)

    if staff_scope["clinic_wide_clinic_ids"]:
        clinic_provider_ids = (
            db.query(models.Provider.id.label("provider_id"))
            .filter(
                models.Provider.clinic_id.in_(
                    staff_scope["clinic_wide_clinic_ids"]
                )
            )
            .subquery()
        )

        clinic_referral_episode_ids = _episode_ids_from_clinic_referrals_subquery(
            db,
            staff_scope["clinic_wide_clinic_ids"],
        )
        clinic_appointment_episode_ids = _episode_ids_from_clinic_appointments_subquery(
            db,
            staff_scope["clinic_wide_clinic_ids"],
        )

        filters.append(
            models.CareEpisode.owner_provider_id.in_(
                select(clinic_provider_ids.c.provider_id)
            )
        )
        filters.append(
            models.CareEpisode.id.in_(
                select(clinic_referral_episode_ids.c.episode_id)
            )
        )
        filters.append(
            models.CareEpisode.id.in_(
                select(clinic_appointment_episode_ids.c.episode_id)
            )
        )

    if staff_scope["doctor_ids"]:
        doctor_episode_ids = _episode_ids_from_doctor_appointments_subquery(
            db,
            staff_scope["doctor_ids"],
        )
        filters.append(
            models.CareEpisode.id.in_(select(doctor_episode_ids.c.episode_id))
        )

    if not filters:
        _raise_not_enough_permissions()

    return (
        db.query(models.CareEpisode)
        .filter(or_(*filters))
        .order_by(models.CareEpisode.id.desc())
        .all()
    )


@router.get("/{episode_id}", response_model=CareEpisodeOut)
def get_episode(
    episode_id: int,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    episode = _get_episode_or_404(db, episode_id)
    _ensure_episode_access(db, episode, current_user)
    return episode


@router.put("/{episode_id}", response_model=CareEpisodeOut)
def update_episode(
    episode_id: int,
    payload: CareEpisodeUpdate,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    episode = _get_episode_or_404(db, episode_id)
    _ensure_episode_write_access(db, episode, current_user)

    data = payload.model_dump(exclude_unset=True)

    if "patient_id" in data:
        patient = (
            db.query(models.Patient)
            .filter(models.Patient.id == data["patient_id"])
            .first()
        )
        if not patient:
            raise HTTPException(status_code=400, detail="Pacientul nu există.")

    for k, v in data.items():
        setattr(episode, k, v)

    db.commit()
    db.refresh(episode)
    return episode


@router.delete("/{episode_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_episode(
    episode_id: int,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    episode = _get_episode_or_404(db, episode_id)
    _ensure_episode_write_access(db, episode, current_user)

    db.delete(episode)
    db.commit()
    return None


@router.get("/{episode_id}/timeline")
def get_timeline(
    episode_id: int,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
) -> Dict[str, Any]:
    episode = _get_episode_or_404(db, episode_id)
    _ensure_episode_access(db, episode, current_user)

    appointments = (
        db.query(models.Appointment)
        .filter(models.Appointment.episode_id == episode.id)
        .order_by(models.Appointment.start_time.asc())
        .all()
    )

    notes = (
        db.query(models.CareNote)
        .filter(models.CareNote.episode_id == episode.id)
        .order_by(models.CareNote.id.asc())
        .all()
    )

    tasks = (
        db.query(models.CareTask)
        .filter(models.CareTask.episode_id == episode.id)
        .order_by(models.CareTask.id.asc())
        .all()
    )

    referrals = (
        db.query(models.Referral)
        .filter(models.Referral.episode_id == episode.id)
        .order_by(models.Referral.id.asc())
        .all()
    )

    documents = (
        db.query(models.MedicalDocument)
        .filter(models.MedicalDocument.episode_id == episode.id)
        .order_by(
            models.MedicalDocument.created_at.asc(),
            models.MedicalDocument.id.asc(),
        )
        .all()
    )

    staff_scope = _build_staff_scope(db, current_user)
    doctor_ids = staff_scope["doctor_ids"]
    clinic_roles = set(staff_scope["clinic_roles"])

    if doctor_ids and not staff_scope["clinic_wide_clinic_ids"]:
        appointments = [
            a for a in appointments if getattr(a, "doctor_id", None) in doctor_ids
        ]

    if current_user.role == "patient":
        notes = []
        tasks = []

    if "reception" in clinic_roles:
        notes = []
        tasks = []
        documents = []

    return jsonable_encoder(
        {
            "episode": episode,
            "appointments": appointments,
            "notes": notes,
            "tasks": tasks,
            "referrals": referrals,
            "documents": documents,
        }
    )


@router.post(
    "/{episode_id}/notes",
    response_model=CareNoteOut,
    status_code=status.HTTP_201_CREATED,
)
def add_note(
    episode_id: int,
    payload: CareNoteCreate,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    episode = _get_episode_or_404(db, episode_id)
    _ensure_episode_write_access(db, episode, current_user)

    staff_scope = _build_staff_scope(db, current_user)
    clinic_roles = set(staff_scope["clinic_roles"])

    if "reception" in clinic_roles:
        raise HTTPException(
            status_code=403,
            detail="Recepția nu poate adăuga note medicale în timeline.",
        )

    note = models.CareNote(
        episode_id=episode.id,
        author_user_id=current_user.id,
        text=payload.text,
    )
    db.add(note)
    db.commit()
    db.refresh(note)
    return note


@router.get("/{episode_id}/notes", response_model=List[CareNoteOut])
def list_notes(
    episode_id: int,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    episode = _get_episode_or_404(db, episode_id)
    _ensure_episode_access(db, episode, current_user)

    if current_user.role == "patient":
        return []

    staff_scope = _build_staff_scope(db, current_user)
    clinic_roles = set(staff_scope["clinic_roles"])

    if "reception" in clinic_roles:
        return []

    return (
        db.query(models.CareNote)
        .filter(models.CareNote.episode_id == episode.id)
        .order_by(models.CareNote.id.asc())
        .all()
    )


@router.post(
    "/{episode_id}/tasks",
    response_model=CareTaskOut,
    status_code=status.HTTP_201_CREATED,
)
def add_task(
    episode_id: int,
    payload: CareTaskCreate,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    episode = _get_episode_or_404(db, episode_id)
    _ensure_episode_write_access(db, episode, current_user)

    staff_scope = _build_staff_scope(db, current_user)
    clinic_roles = set(staff_scope["clinic_roles"])

    if "reception" in clinic_roles:
        raise HTTPException(
            status_code=403,
            detail="Recepția nu poate adăuga taskuri medicale în timeline.",
        )

    task = models.CareTask(
        episode_id=episode.id,
        title=payload.title,
        due_at=payload.due_at,
        assigned_to_role=payload.assigned_to_role,
        status="todo",
    )
    db.add(task)
    db.commit()
    db.refresh(task)
    return task


@router.get("/{episode_id}/tasks", response_model=List[CareTaskOut])
def list_tasks(
    episode_id: int,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    episode = _get_episode_or_404(db, episode_id)
    _ensure_episode_access(db, episode, current_user)

    if current_user.role == "patient":
        return []

    staff_scope = _build_staff_scope(db, current_user)
    clinic_roles = set(staff_scope["clinic_roles"])

    if "reception" in clinic_roles:
        return []

    return (
        db.query(models.CareTask)
        .filter(models.CareTask.episode_id == episode.id)
        .order_by(models.CareTask.id.asc())
        .all()
    )


@router.put("/tasks/{task_id}", response_model=CareTaskOut)
def update_task(
    task_id: int,
    payload: CareTaskUpdate,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    task = db.query(models.CareTask).filter(models.CareTask.id == task_id).first()
    if not task:
        raise HTTPException(status_code=404, detail="Taskul nu a fost găsit.")

    episode = _get_episode_or_404(db, task.episode_id)
    _ensure_episode_write_access(db, episode, current_user)

    staff_scope = _build_staff_scope(db, current_user)
    clinic_roles = set(staff_scope["clinic_roles"])

    if "reception" in clinic_roles:
        raise HTTPException(
            status_code=403,
            detail="Recepția nu poate modifica taskuri medicale.",
        )

    data = payload.model_dump(exclude_unset=True)
    for k, v in data.items():
        setattr(task, k, v)

    db.commit()
    db.refresh(task)
    return task