# Path: backend/app/api/v1/appointments.py

from datetime import datetime, timedelta, timezone
from typing import List, Optional, Union

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.core.security import get_current_provider_for_user, get_current_user
from app.core.subscription import ensure_clinic_has_active_subscription
from app.db import get_db
from app.integrations.google_calendar.client import (
    create_calendar_event,
    integration_has_usable_tokens,
    query_freebusy,
)
from app.models.appointment import Appointment as AppointmentModel
from app.models.care_episode import CareEpisode as CareEpisodeModel
from app.models.care_task import CareTask as CareTaskModel
from app.models.clinic_membership import ClinicMembership as ClinicMembershipModel
from app.models.google_calendar_integration import GoogleCalendarIntegration
from app.models.patient import Patient as PatientModel
from app.models.provider import Provider as ProviderModel
from app.models.provider_doctor import ProviderDoctor as ProviderDoctorModel
from app.models.referral import Referral as ReferralModel
from app.schemas.appointment import Appointment, AppointmentCreate, AppointmentUpdate
from app.schemas.care_task import CareTaskCreate, CareTaskOut

router = APIRouter(prefix="/appointments", tags=["appointments"])

REFERRAL_ACCESS_STATUSES = ("accepted", "in_progress", "completed")
INACTIVE_EPISODE_STATUSES = ("completed", "closed", "archived")
BLOCKING_APPOINTMENT_STATUSES = ("scheduled", "in_progress")
PROVIDER_VISIBLE_APPOINTMENT_STATUSES = ("scheduled", "in_progress", "completed")

CLINIC_WIDE_VIEW_ROLES = {"clinic_admin", "reception", "receptionist"}
CLINIC_WIDE_BOOKING_ROLES = {"clinic_admin", "reception", "receptionist"}
DOCTOR_ROLE = "doctor"
ASSISTANT_ROLE = "assistant"
STAFF_VIEW_ROLES = CLINIC_WIDE_VIEW_ROLES | {DOCTOR_ROLE, ASSISTANT_ROLE}
STAFF_BOOKING_ROLES = CLINIC_WIDE_BOOKING_ROLES | {DOCTOR_ROLE, ASSISTANT_ROLE}


def _normalize_clinic_role(value: Optional[str]) -> Optional[str]:
    if value == "receptionist":
        return "reception"
    return value


def _raise_platform_admin_appointment_access_denied() -> None:
    raise HTTPException(
        status_code=403,
        detail=(
            "Această zonă conține date medicale și operaționale ale pacienților. "
            "Administratorul platformei poate vedea doar informații minime prin panoul de administrare."
        ),
    )


def _get_my_patient_profile(db: Session, current_user) -> PatientModel:
    patient = db.query(PatientModel).filter(PatientModel.user_id == current_user.id).first()
    if not patient:
        raise HTTPException(status_code=404, detail="Profilul de pacient nu este asociat acestui cont.")
    return patient


def _get_my_provider_profile(db: Session, current_user) -> ProviderModel:
    provider = get_current_provider_for_user(db, current_user)
    if getattr(provider, "status", None) != "approved" and current_user.role != "admin":
        raise HTTPException(status_code=403, detail="Profilul de furnizor nu este aprobat.")
    return provider


def _get_active_staff_memberships(db: Session, current_user) -> List[ClinicMembershipModel]:
    return (
        db.query(ClinicMembershipModel)
        .filter(
            ClinicMembershipModel.user_id == current_user.id,
            ClinicMembershipModel.is_active == True,  # noqa: E712
        )
        .all()
    )


def _get_staff_scope(db: Session, current_user) -> dict:
    memberships = _get_active_staff_memberships(db, current_user)

    clinic_ids: List[int] = []
    doctor_ids: List[int] = []
    assistant_clinic_ids: List[int] = []
    has_clinic_wide_access = False

    for membership in memberships:
        role = _normalize_clinic_role(getattr(membership, "role", None))
        clinic_id = getattr(membership, "clinic_id", None)
        provider_doctor_id = getattr(membership, "provider_doctor_id", None)

        if role not in STAFF_VIEW_ROLES or clinic_id is None:
            continue

        if clinic_id not in clinic_ids:
            clinic_ids.append(clinic_id)

        if role in CLINIC_WIDE_VIEW_ROLES:
            has_clinic_wide_access = True

        if role == DOCTOR_ROLE and provider_doctor_id is not None and provider_doctor_id not in doctor_ids:
            doctor_ids.append(provider_doctor_id)

        if role == ASSISTANT_ROLE and clinic_id not in assistant_clinic_ids:
            assistant_clinic_ids.append(clinic_id)

    return {
        "clinic_ids": clinic_ids,
        "doctor_ids": doctor_ids,
        "assistant_clinic_ids": assistant_clinic_ids,
        "has_clinic_wide_access": has_clinic_wide_access,
    }


def _has_staff_booking_access(db: Session, current_user) -> bool:
    memberships = _get_active_staff_memberships(db, current_user)

    for membership in memberships:
        role = _normalize_clinic_role(getattr(membership, "role", None))
        if role in STAFF_BOOKING_ROLES:
            return True

    return False


def _get_accessible_clinic_ids(db: Session, current_user) -> List[int]:
    scope = _get_staff_scope(db, current_user)
    return scope["clinic_ids"]


def _ensure_provider_clinic_access(db: Session, provider: ProviderModel, current_user) -> None:
    if current_user.role == "admin":
        _raise_platform_admin_appointment_access_denied()

    provider_clinic_id = getattr(provider, "clinic_id", None)
    if provider_clinic_id is None:
        raise HTTPException(status_code=403, detail="Provider is not linked to a clinic")

    accessible_clinic_ids = _get_accessible_clinic_ids(db, current_user)
    if provider_clinic_id not in accessible_clinic_ids:
        raise HTTPException(status_code=403, detail="Not allowed for this clinic")


def _ensure_doctor_assignment_allowed(
    db: Session,
    *,
    current_user,
    provider_id: int,
    doctor_id: Optional[int],
) -> None:
    if current_user.role == "admin":
        _raise_platform_admin_appointment_access_denied()

    scope = _get_staff_scope(db, current_user)

    if scope["has_clinic_wide_access"]:
        return

    allowed_doctor_ids = scope["doctor_ids"]

    if allowed_doctor_ids:
        if doctor_id is None:
            raise HTTPException(
                status_code=403,
                detail="Doctor staff can only manage appointments assigned to their own doctor profile",
            )

        if doctor_id not in allowed_doctor_ids:
            raise HTTPException(status_code=403, detail="You can only manage your own appointments")

        doctor = (
            db.query(ProviderDoctorModel)
            .filter(
                ProviderDoctorModel.id == doctor_id,
                ProviderDoctorModel.provider_id == provider_id,
                ProviderDoctorModel.is_active == True,  # noqa: E712
            )
            .first()
        )
        if not doctor:
            raise HTTPException(status_code=400, detail="Doctor does not belong to this provider")
        return

    if scope["assistant_clinic_ids"]:
        raise HTTPException(
            status_code=403,
            detail="Assistant users can only work on already assigned workflow items.",
        )


def _has_referral_access(db: Session, episode_id: int, to_provider_id: int) -> bool:
    ref = (
        db.query(ReferralModel)
        .filter(
            ReferralModel.episode_id == episode_id,
            ReferralModel.to_provider_id == to_provider_id,
            ReferralModel.status.in_(REFERRAL_ACCESS_STATUSES),
        )
        .first()
    )
    return ref is not None


def _ensure_episode_access_for_provider(db: Session, episode_id: int, current_user) -> None:
    if current_user.role == "admin":
        _raise_platform_admin_appointment_access_denied()

    provider = _get_my_provider_profile(db, current_user)
    episode = db.query(CareEpisodeModel).filter(CareEpisodeModel.id == episode_id).first()
    if not episode:
        raise HTTPException(status_code=400, detail="Care episode does not exist")

    if episode.owner_provider_id == provider.id:
        return

    if _has_referral_access(db, episode_id, provider.id):
        return

    raise HTTPException(status_code=403, detail="Not allowed for this care episode")


def _provider_visible_appointments_query(db: Session, provider_id: int):
    referred_episode_ids = (
        select(ReferralModel.episode_id)
        .where(
            ReferralModel.to_provider_id == provider_id,
            ReferralModel.status.in_(REFERRAL_ACCESS_STATUSES),
        )
    )

    return (
        db.query(AppointmentModel)
        .filter(AppointmentModel.status.in_(PROVIDER_VISIBLE_APPOINTMENT_STATUSES))
        .filter(
            or_(
                AppointmentModel.provider_id == provider_id,
                AppointmentModel.episode_id.in_(referred_episode_ids),
            )
        )
    )


def _clinic_visible_appointments_query(
    db: Session,
    clinic_ids: List[int],
    doctor_ids: Optional[List[int]] = None,
    clinic_wide: bool = True,
):
    provider_ids = select(ProviderModel.id).where(ProviderModel.clinic_id.in_(clinic_ids))

    query = (
        db.query(AppointmentModel)
        .filter(AppointmentModel.status.in_(PROVIDER_VISIBLE_APPOINTMENT_STATUSES))
        .filter(
            or_(
                AppointmentModel.clinic_id.in_(clinic_ids),
                AppointmentModel.provider_id.in_(provider_ids),
            )
        )
    )

    if not clinic_wide:
        if not doctor_ids:
            return query.filter(False)
        query = query.filter(AppointmentModel.doctor_id.in_(doctor_ids))

    return query


def _naive_dt(v: Optional[Union[str, datetime]]) -> Optional[datetime]:
    if v is None:
        return None

    if isinstance(v, str):
        s = v.replace("Z", "+00:00")
        v = datetime.fromisoformat(s)

    if isinstance(v, datetime) and v.tzinfo is not None:
        v = v.astimezone(timezone.utc).replace(tzinfo=None)

    return v


def _patient_display_name(patient: Optional[PatientModel]) -> Optional[str]:
    if not patient:
        return None

    first_name = getattr(patient, "first_name", None) or ""
    last_name = getattr(patient, "last_name", None) or ""
    full = f"{first_name} {last_name}".strip()

    if full:
        return full

    return getattr(patient, "email", None) or f"Patient #{getattr(patient, 'id', '?')}"


def _provider_display_name(provider: Optional[ProviderModel]) -> Optional[str]:
    if not provider:
        return None
    return getattr(provider, "name", None) or f"Provider #{getattr(provider, 'id', '?')}"


def _doctor_display_name(doctor: Optional[ProviderDoctorModel]) -> Optional[str]:
    if not doctor:
        return None

    title = getattr(doctor, "title", None) or ""
    name = getattr(doctor, "name", None) or ""
    full = f"{title} {name}".strip()

    if full:
        return full

    return f"Doctor #{getattr(doctor, 'id', '?')}"


def _serialize_appointment(db: Session, appointment: AppointmentModel) -> dict:
    patient = None
    provider = None
    doctor = None

    if appointment.patient_id:
        patient = db.query(PatientModel).filter(PatientModel.id == appointment.patient_id).first()

    if appointment.provider_id:
        provider = db.query(ProviderModel).filter(ProviderModel.id == appointment.provider_id).first()

    if getattr(appointment, "doctor_id", None):
        doctor = db.query(ProviderDoctorModel).filter(ProviderDoctorModel.id == appointment.doctor_id).first()

    return {
        "id": appointment.id,
        "patient_id": appointment.patient_id,
        "provider_id": appointment.provider_id,
        "doctor_id": getattr(appointment, "doctor_id", None),
        "episode_id": appointment.episode_id,
        "clinic_id": getattr(appointment, "clinic_id", None),
        "created_by_user_id": getattr(appointment, "created_by_user_id", None),
        "google_calendar_integration_id": getattr(appointment, "google_calendar_integration_id", None),
        "google_event_id": getattr(appointment, "google_event_id", None),
        "google_sync_status": getattr(appointment, "google_sync_status", None),
        "google_sync_error": getattr(appointment, "google_sync_error", None),
        "start_time": appointment.start_time,
        "end_time": appointment.end_time,
        "status": appointment.status,
        "notes": appointment.notes,
        "fhir_id": appointment.fhir_id,
        "created_at": appointment.created_at,
        "patient_name": _patient_display_name(patient),
        "provider_name": _provider_display_name(provider),
        "doctor_name": _doctor_display_name(doctor),
    }


def _serialize_appointments(db: Session, appointments: List[AppointmentModel]) -> List[dict]:
    return [_serialize_appointment(db, a) for a in appointments]


def _find_active_episode_for_pair(
    db: Session,
    patient_id: int,
    provider_id: int,
) -> Optional[CareEpisodeModel]:
    return (
        db.query(CareEpisodeModel)
        .filter(
            CareEpisodeModel.patient_id == patient_id,
            CareEpisodeModel.owner_provider_id == provider_id,
            CareEpisodeModel.status.notin_(INACTIVE_EPISODE_STATUSES),
        )
        .order_by(CareEpisodeModel.id.desc())
        .first()
    )


def _get_or_create_episode_for_pair(
    db: Session,
    patient_id: int,
    provider_id: int,
) -> CareEpisodeModel:
    episode = _find_active_episode_for_pair(db, patient_id=patient_id, provider_id=provider_id)
    if episode:
        return episode

    provider = db.query(ProviderModel).filter(ProviderModel.id == provider_id).first()
    patient = db.query(PatientModel).filter(PatientModel.id == patient_id).first()

    provider_name = _provider_display_name(provider) or f"Provider #{provider_id}"
    patient_name = _patient_display_name(patient) or f"Patient #{patient_id}"

    episode = CareEpisodeModel(
        patient_id=patient_id,
        owner_provider_id=provider_id,
        title=f"{provider_name} • {patient_name}",
        status="open",
    )
    db.add(episode)
    db.flush()
    return episode


def _get_appointment_or_404(db: Session, appointment_id: int) -> AppointmentModel:
    appointment = db.query(AppointmentModel).filter(AppointmentModel.id == appointment_id).first()
    if not appointment:
        raise HTTPException(status_code=404, detail="Appointment not found")
    return appointment


def _appointment_belongs_to_staff_clinic(db: Session, appointment: AppointmentModel, current_user) -> bool:
    scope = _get_staff_scope(db, current_user)
    clinic_ids = scope["clinic_ids"]
    allowed_doctor_ids = scope["doctor_ids"]
    has_clinic_wide_access = scope["has_clinic_wide_access"]

    if not clinic_ids:
        return False

    appointment_clinic_id = getattr(appointment, "clinic_id", None)
    provider = db.query(ProviderModel).filter(ProviderModel.id == appointment.provider_id).first()
    provider_clinic_id = getattr(provider, "clinic_id", None) if provider else None

    if appointment_clinic_id not in clinic_ids and provider_clinic_id not in clinic_ids:
        return False

    if has_clinic_wide_access:
        return True

    appointment_doctor_id = getattr(appointment, "doctor_id", None)
    if appointment_doctor_id is None:
        return False

    return appointment_doctor_id in allowed_doctor_ids


def _appointment_is_in_staff_clinic(db: Session, appointment: AppointmentModel, current_user) -> bool:
    scope = _get_staff_scope(db, current_user)
    clinic_ids = scope["clinic_ids"]

    if not clinic_ids:
        return False

    appointment_clinic_id = getattr(appointment, "clinic_id", None)

    provider_clinic_id = None
    if appointment.provider_id is not None:
        provider = db.query(ProviderModel).filter(ProviderModel.id == appointment.provider_id).first()
        provider_clinic_id = getattr(provider, "clinic_id", None) if provider else None

    return appointment_clinic_id in clinic_ids or provider_clinic_id in clinic_ids


def _ensure_appointment_access(db: Session, appointment: AppointmentModel, current_user) -> None:
    if current_user.role == "admin":
        _raise_platform_admin_appointment_access_denied()

    if current_user.role == "patient":
        patient = _get_my_patient_profile(db, current_user)
        if appointment.patient_id != patient.id:
            raise HTTPException(status_code=403, detail="Not allowed")
        return

    scope = _get_staff_scope(db, current_user)

    if scope["clinic_ids"]:
        if _appointment_belongs_to_staff_clinic(db, appointment, current_user):
            return

        if _appointment_is_in_staff_clinic(db, appointment, current_user):
            raise HTTPException(
                status_code=403,
                detail="You do not have enough access for this appointment.",
            )

    try:
        provider = _get_my_provider_profile(db, current_user)
    except HTTPException:
        raise HTTPException(status_code=403, detail="Not enough permissions")

    if appointment.provider_id == provider.id:
        return

    if appointment.episode_id is not None and _has_referral_access(db, appointment.episode_id, provider.id):
        return

    raise HTTPException(status_code=403, detail="Not allowed")


def _ensure_appointment_has_episode(db: Session, appointment: AppointmentModel) -> AppointmentModel:
    if appointment.episode_id is not None:
        return appointment

    episode = _get_or_create_episode_for_pair(
        db,
        patient_id=appointment.patient_id,
        provider_id=appointment.provider_id,
    )
    appointment.episode_id = episode.id
    db.commit()
    db.refresh(appointment)
    return appointment


def _validate_doctor_belongs_to_provider(
    db: Session,
    provider_id: int,
    doctor_id: Optional[int],
) -> None:
    if doctor_id is None:
        return

    doctor = (
        db.query(ProviderDoctorModel)
        .filter(
            ProviderDoctorModel.id == doctor_id,
            ProviderDoctorModel.provider_id == provider_id,
            ProviderDoctorModel.is_active == True,  # noqa: E712
        )
        .first()
    )
    if not doctor:
        raise HTTPException(status_code=400, detail="Doctor does not belong to this provider")


def _ensure_no_appointment_conflict(
    db: Session,
    *,
    provider_id: int,
    doctor_id: Optional[int],
    start_time: datetime,
    end_time: Optional[datetime],
    ignore_appointment_id: Optional[int] = None,
) -> None:
    if end_time is None:
        end_time = start_time + timedelta(minutes=30)

    query = db.query(AppointmentModel).filter(
        AppointmentModel.provider_id == provider_id,
        AppointmentModel.status.in_(BLOCKING_APPOINTMENT_STATUSES),
        AppointmentModel.start_time < end_time,
        AppointmentModel.end_time > start_time,
    )

    if doctor_id is None:
        query = query.filter(AppointmentModel.doctor_id.is_(None))
    else:
        query = query.filter(AppointmentModel.doctor_id == doctor_id)

    if ignore_appointment_id is not None:
        query = query.filter(AppointmentModel.id != ignore_appointment_id)

    conflict = query.first()
    if conflict:
        raise HTTPException(status_code=409, detail="This time slot is already booked")


def _get_google_calendar_mapping_for_booking(
    db: Session,
    *,
    provider_id: int,
    doctor_id: Optional[int],
) -> Optional[GoogleCalendarIntegration]:
    query = (
        db.query(GoogleCalendarIntegration)
        .filter(
            GoogleCalendarIntegration.provider_id == provider_id,
            GoogleCalendarIntegration.is_active == True,  # noqa: E712
            GoogleCalendarIntegration.status.in_(["configured", "connected", "active"]),
        )
    )

    if doctor_id is not None:
        doctor_mapping = (
            query.filter(GoogleCalendarIntegration.doctor_id == doctor_id)
            .order_by(GoogleCalendarIntegration.id.asc())
            .first()
        )
        if doctor_mapping:
            return doctor_mapping

    return (
        query.filter(GoogleCalendarIntegration.doctor_id.is_(None))
        .order_by(GoogleCalendarIntegration.id.asc())
        .first()
    )


def _parse_google_datetime(value: str) -> Optional[datetime]:
    if not value:
        return None

    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None

    return _naive_dt(parsed)


def _ensure_google_calendar_slot_free(
    mapping: GoogleCalendarIntegration,
    *,
    start_time: datetime,
    end_time: datetime,
) -> None:
    if not integration_has_usable_tokens(mapping):
        return

    busy_slots = query_freebusy(
        mapping,
        time_min=start_time,
        time_max=end_time,
    )

    for busy in busy_slots:
        busy_start = _parse_google_datetime(str(busy.get("start") or ""))
        busy_end = _parse_google_datetime(str(busy.get("end") or ""))

        if busy_start is None or busy_end is None:
            continue

        if start_time < busy_end and busy_start < end_time:
            raise HTTPException(status_code=409, detail="This time slot is already busy in Google Calendar")


def _build_google_event_summary(
    *,
    patient_name: Optional[str],
    provider_name: Optional[str],
    doctor_name: Optional[str],
) -> str:
    parts = ["MediCalend"]
    if patient_name:
        parts.append(patient_name)
    if doctor_name:
        parts.append(doctor_name)
    elif provider_name:
        parts.append(provider_name)

    return " • ".join(parts)


def _build_google_event_description(
    *,
    appointment_id: Optional[int],
    patient: Optional[PatientModel],
    provider: Optional[ProviderModel],
    doctor: Optional[ProviderDoctorModel],
    notes: Optional[str],
) -> str:
    lines = [
        "Created by MediCalend.",
        "",
        f"Appointment ID: {appointment_id or 'pending'}",
    ]

    if patient:
        lines.append(f"Patient: {_patient_display_name(patient)}")
        if getattr(patient, "phone", None):
            lines.append(f"Patient phone: {patient.phone}")
        if getattr(patient, "email", None):
            lines.append(f"Patient email: {patient.email}")

    if provider:
        lines.append(f"Provider: {_provider_display_name(provider)}")

    if doctor:
        lines.append(f"Doctor: {_doctor_display_name(doctor)}")

    if notes:
        lines.extend(["", "Notes:", notes])

    return "\n".join(lines)


def _sync_appointment_to_google_calendar(
    db: Session,
    *,
    appointment: AppointmentModel,
    patient: Optional[PatientModel],
    provider: Optional[ProviderModel],
    doctor: Optional[ProviderDoctorModel],
) -> AppointmentModel:
    mapping = _get_google_calendar_mapping_for_booking(
        db,
        provider_id=appointment.provider_id,
        doctor_id=getattr(appointment, "doctor_id", None),
    )

    if not mapping:
        appointment.google_sync_status = "not_configured"
        db.add(appointment)
        db.flush()
        return appointment

    appointment.google_calendar_integration_id = mapping.id

    if not integration_has_usable_tokens(mapping):
        appointment.google_sync_status = "not_configured"
        appointment.google_sync_error = "Google Calendar OAuth tokens are not configured."
        db.add(appointment)
        db.flush()
        return appointment

    start_time = _naive_dt(appointment.start_time)
    end_time = _naive_dt(appointment.end_time) or (start_time + timedelta(minutes=30))

    if start_time is None:
        appointment.google_sync_status = "failed"
        appointment.google_sync_error = "Appointment start_time is missing."
        db.add(appointment)
        db.flush()
        return appointment

    _ensure_google_calendar_slot_free(
        mapping,
        start_time=start_time,
        end_time=end_time,
    )

    try:
        event = create_calendar_event(
            mapping,
            summary=_build_google_event_summary(
                patient_name=_patient_display_name(patient),
                provider_name=_provider_display_name(provider),
                doctor_name=_doctor_display_name(doctor),
            ),
            description=_build_google_event_description(
                appointment_id=appointment.id,
                patient=patient,
                provider=provider,
                doctor=doctor,
                notes=appointment.notes,
            ),
            start_time=start_time,
            end_time=end_time,
            timezone_name="Europe/Bucharest",
        )
    except HTTPException:
        raise
    except Exception as exc:
        appointment.google_sync_status = "failed"
        appointment.google_sync_error = str(exc)
        db.add(appointment)
        db.flush()
        raise HTTPException(
            status_code=502,
            detail="Google Calendar event creation failed. Appointment was not confirmed.",
        ) from exc

    appointment.google_event_id = event.get("id")
    appointment.google_sync_status = "synced"
    appointment.google_sync_error = None
    db.add(appointment)
    db.flush()
    return appointment


def _create_appointment_with_google_sync(
    db: Session,
    *,
    data: dict,
    patient: PatientModel,
    provider: ProviderModel,
    doctor: Optional[ProviderDoctorModel],
) -> AppointmentModel:
    appointment = AppointmentModel(**data)
    db.add(appointment)
    db.flush()

    try:
        appointment = _sync_appointment_to_google_calendar(
            db,
            appointment=appointment,
            patient=patient,
            provider=provider,
            doctor=doctor,
        )
    except HTTPException:
        db.rollback()
        raise

    db.commit()
    db.refresh(appointment)
    return appointment


@router.get("/", response_model=List[Appointment])
def list_appointments(
    skip: int = 0,
    limit: int = 100,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    if current_user.role == "admin":
        _raise_platform_admin_appointment_access_denied()

    if current_user.role == "patient":
        patient = _get_my_patient_profile(db, current_user)
        rows = (
            db.query(AppointmentModel)
            .filter(AppointmentModel.patient_id == patient.id)
            .order_by(AppointmentModel.start_time.desc())
            .offset(skip)
            .limit(limit)
            .all()
        )
        return _serialize_appointments(db, rows)

    scope = _get_staff_scope(db, current_user)
    clinic_ids = scope["clinic_ids"]

    if clinic_ids:
        rows = (
            _clinic_visible_appointments_query(
                db,
                clinic_ids,
                doctor_ids=scope["doctor_ids"],
                clinic_wide=scope["has_clinic_wide_access"],
            )
            .order_by(AppointmentModel.start_time.desc())
            .offset(skip)
            .limit(limit)
            .all()
        )
        return _serialize_appointments(db, rows)

    provider = _get_my_provider_profile(db, current_user)
    rows = (
        _provider_visible_appointments_query(db, provider.id)
        .order_by(AppointmentModel.start_time.desc())
        .offset(skip)
        .limit(limit)
        .all()
    )
    return _serialize_appointments(db, rows)


@router.get("/search", response_model=List[Appointment])
def search_appointments(
    patient_id: Optional[int] = None,
    provider_id: Optional[int] = None,
    doctor_id: Optional[int] = None,
    episode_id: Optional[int] = None,
    status_value: Optional[str] = None,
    start_from: Optional[datetime] = None,
    start_to: Optional[datetime] = None,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    if current_user.role == "admin":
        _raise_platform_admin_appointment_access_denied()

    if current_user.role == "patient":
        my_patient = _get_my_patient_profile(db, current_user)
        query = db.query(AppointmentModel).filter(AppointmentModel.patient_id == my_patient.id)
        patient_id = None

    else:
        scope = _get_staff_scope(db, current_user)
        clinic_ids = scope["clinic_ids"]

        if clinic_ids:
            query = _clinic_visible_appointments_query(
                db,
                clinic_ids,
                doctor_ids=scope["doctor_ids"],
                clinic_wide=scope["has_clinic_wide_access"],
            )

            if not scope["has_clinic_wide_access"]:
                doctor_id = None
        else:
            my_provider = _get_my_provider_profile(db, current_user)
            query = _provider_visible_appointments_query(db, my_provider.id)

    if patient_id is not None:
        query = query.filter(AppointmentModel.patient_id == patient_id)

    if provider_id is not None:
        query = query.filter(AppointmentModel.provider_id == provider_id)

    if doctor_id is not None:
        query = query.filter(AppointmentModel.doctor_id == doctor_id)

    if episode_id is not None:
        query = query.filter(AppointmentModel.episode_id == episode_id)

    if status_value:
        query = query.filter(AppointmentModel.status == status_value)

    if start_from:
        start_from = _naive_dt(start_from)
        query = query.filter(AppointmentModel.start_time >= start_from)

    if start_to:
        start_to = _naive_dt(start_to)
        query = query.filter(AppointmentModel.start_time <= start_to)

    rows = query.order_by(AppointmentModel.start_time.desc()).all()
    return _serialize_appointments(db, rows)


@router.get("/{appointment_id}", response_model=Appointment)
def get_appointment(
    appointment_id: int,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    appointment = db.query(AppointmentModel).filter(AppointmentModel.id == appointment_id).first()
    if not appointment:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Appointment not found")

    _ensure_appointment_access(db, appointment, current_user)
    return _serialize_appointment(db, appointment)


@router.post("/", response_model=Appointment, status_code=status.HTTP_201_CREATED)
def create_appointment(
    payload: AppointmentCreate,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    if current_user.role == "admin":
        _raise_platform_admin_appointment_access_denied()

    if current_user.role == "patient":
        my_patient = _get_my_patient_profile(db, current_user)

        if getattr(payload, "patient_id", None) is not None and payload.patient_id != my_patient.id:
            raise HTTPException(status_code=403, detail="You can only create appointments for yourself")

        data = payload.model_dump()
        data["patient_id"] = my_patient.id
        data["created_by_user_id"] = current_user.id
        data["start_time"] = _naive_dt(data.get("start_time"))
        data["end_time"] = _naive_dt(data.get("end_time"))

        provider = db.query(ProviderModel).filter(ProviderModel.id == data["provider_id"]).first()
        if not provider:
            raise HTTPException(status_code=400, detail="Provider does not exist")
        if getattr(provider, "status", None) != "approved":
            raise HTTPException(status_code=403, detail="Provider not approved")
        if getattr(provider, "is_active", True) is False:
            raise HTTPException(status_code=403, detail="Provider inactive")

        data["clinic_id"] = getattr(provider, "clinic_id", None)
        if data["clinic_id"]:
            ensure_clinic_has_active_subscription(db, data["clinic_id"])

        _validate_doctor_belongs_to_provider(db, data["provider_id"], data.get("doctor_id"))

        doctor = None
        if data.get("doctor_id") is not None:
            doctor = db.query(ProviderDoctorModel).filter(ProviderDoctorModel.id == data["doctor_id"]).first()

        if data.get("episode_id") is not None:
            ep = db.query(CareEpisodeModel).filter(CareEpisodeModel.id == data["episode_id"]).first()
            if not ep:
                raise HTTPException(status_code=400, detail="Care episode does not exist")
            if ep.patient_id != my_patient.id:
                raise HTTPException(status_code=403, detail="You can only use your own care episodes")
        else:
            ep = _get_or_create_episode_for_pair(
                db,
                patient_id=data["patient_id"],
                provider_id=data["provider_id"],
            )
            data["episode_id"] = ep.id

        if not data.get("end_time") and data.get("start_time"):
            data["end_time"] = data["start_time"] + timedelta(minutes=30)

        _ensure_no_appointment_conflict(
            db,
            provider_id=data["provider_id"],
            doctor_id=data.get("doctor_id"),
            start_time=data["start_time"],
            end_time=data.get("end_time"),
        )

        if not data.get("status"):
            data["status"] = "scheduled"

        appointment = _create_appointment_with_google_sync(
            db,
            data=data,
            patient=my_patient,
            provider=provider,
            doctor=doctor,
        )
        return _serialize_appointment(db, appointment)

    if not _has_staff_booking_access(db, current_user):
        try:
            _get_my_provider_profile(db, current_user)
        except HTTPException:
            raise HTTPException(status_code=403, detail="Not enough permissions")

    patient = db.query(PatientModel).filter(PatientModel.id == payload.patient_id).first()
    if not patient:
        raise HTTPException(status_code=400, detail="Patient does not exist")

    provider = db.query(ProviderModel).filter(ProviderModel.id == payload.provider_id).first()
    if not provider:
        raise HTTPException(status_code=400, detail="Provider does not exist")

    _validate_doctor_belongs_to_provider(db, payload.provider_id, payload.doctor_id)

    doctor = None
    if payload.doctor_id is not None:
        doctor = db.query(ProviderDoctorModel).filter(ProviderDoctorModel.id == payload.doctor_id).first()

    scope = _get_staff_scope(db, current_user)
    clinic_ids = scope["clinic_ids"]

    if clinic_ids:
        _ensure_provider_clinic_access(db, provider, current_user)
        _ensure_doctor_assignment_allowed(
            db,
            current_user=current_user,
            provider_id=payload.provider_id,
            doctor_id=payload.doctor_id,
        )
    else:
        my_provider = _get_my_provider_profile(db, current_user)
        if payload.provider_id != my_provider.id:
            raise HTTPException(
                status_code=403,
                detail="You can only create appointments for your own provider profile",
            )

    if payload.episode_id is not None:
        _ensure_episode_access_for_provider(db, payload.episode_id, current_user)

    if payload.episode_id is not None:
        ep = db.query(CareEpisodeModel).filter(CareEpisodeModel.id == payload.episode_id).first()
        if not ep:
            raise HTTPException(status_code=400, detail="Care episode does not exist")
    else:
        ep = _get_or_create_episode_for_pair(
            db,
            patient_id=payload.patient_id,
            provider_id=payload.provider_id,
        )

    data = payload.model_dump()
    data["episode_id"] = ep.id
    data["start_time"] = _naive_dt(data.get("start_time"))
    data["end_time"] = _naive_dt(data.get("end_time"))
    data["created_by_user_id"] = current_user.id
    data["clinic_id"] = getattr(provider, "clinic_id", None)

    if data["clinic_id"]:
        ensure_clinic_has_active_subscription(db, data["clinic_id"])

    if not data.get("end_time") and data.get("start_time"):
        data["end_time"] = data["start_time"] + timedelta(minutes=30)

    _ensure_no_appointment_conflict(
        db,
        provider_id=data["provider_id"],
        doctor_id=data.get("doctor_id"),
        start_time=data["start_time"],
        end_time=data.get("end_time"),
    )

    if not data.get("status"):
        data["status"] = "scheduled"

    appointment = _create_appointment_with_google_sync(
        db,
        data=data,
        patient=patient,
        provider=provider,
        doctor=doctor,
    )
    return _serialize_appointment(db, appointment)


@router.get("/{appointment_id}/tasks", response_model=List[CareTaskOut])
def list_appointment_tasks(
    appointment_id: int,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    appointment = _get_appointment_or_404(db, appointment_id)
    _ensure_appointment_access(db, appointment, current_user)

    rows = (
        db.query(CareTaskModel)
        .filter(CareTaskModel.appointment_id == appointment.id)
        .order_by(CareTaskModel.id.asc())
        .all()
    )
    return rows


@router.post("/{appointment_id}/tasks", response_model=CareTaskOut, status_code=status.HTTP_201_CREATED)
def add_appointment_task(
    appointment_id: int,
    payload: CareTaskCreate,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    if current_user.role in ("admin", "patient"):
        raise HTTPException(status_code=403, detail="Not enough permissions")

    appointment = _get_appointment_or_404(db, appointment_id)
    _ensure_appointment_access(db, appointment, current_user)

    appointment = _ensure_appointment_has_episode(db, appointment)

    task = CareTaskModel(
        episode_id=appointment.episode_id,
        appointment_id=appointment.id,
        title=payload.title,
        due_at=payload.due_at,
        assigned_to_role=payload.assigned_to_role,
        status="todo",
    )
    db.add(task)
    db.commit()
    db.refresh(task)
    return task


@router.put("/{appointment_id}", response_model=Appointment)
def update_appointment(
    appointment_id: int,
    payload: AppointmentUpdate,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    appointment = db.query(AppointmentModel).filter(AppointmentModel.id == appointment_id).first()
    if not appointment:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Appointment not found")

    _ensure_appointment_access(db, appointment, current_user)

    update_data = payload.model_dump(exclude_unset=True)

    if current_user.role == "patient":
        allowed_patient_fields = {"status"}
        forbidden_fields = set(update_data.keys()) - allowed_patient_fields
        if forbidden_fields:
            raise HTTPException(
                status_code=403,
                detail="Patients can only cancel their own appointments from this endpoint.",
            )

        if update_data.get("status") != "canceled":
            raise HTTPException(
                status_code=403,
                detail="Patients can only change appointment status to canceled.",
            )

        if appointment.status in {"completed", "canceled"}:
            raise HTTPException(
                status_code=409,
                detail=f"Appointment is final ({appointment.status}) and cannot be changed",
            )

        appointment.status = "canceled"
        db.commit()
        db.refresh(appointment)
        return _serialize_appointment(db, appointment)

    final_statuses = {"completed", "canceled"}
    if appointment.status in final_statuses and "status" in update_data:
        incoming = str(update_data["status"])
        if incoming != appointment.status:
            raise HTTPException(
                status_code=409,
                detail=f"Appointment is final ({appointment.status}) and cannot be changed",
            )

    allowed_transitions = {
        "scheduled": {"in_progress", "completed", "canceled"},
        "in_progress": {"completed", "canceled"},
        "completed": set(),
        "canceled": set(),
    }

    if "status" in update_data:
        curr = str(appointment.status or "scheduled")
        nxt = str(update_data["status"])
        if nxt != curr and nxt not in allowed_transitions.get(curr, set()):
            raise HTTPException(status_code=409, detail=f"Invalid status transition: {curr} -> {nxt}")

    if "start_time" in update_data:
        update_data["start_time"] = _naive_dt(update_data.get("start_time"))
    if "end_time" in update_data:
        update_data["end_time"] = _naive_dt(update_data.get("end_time"))

    new_provider_id = update_data.get("provider_id", appointment.provider_id)
    new_doctor_id = update_data.get("doctor_id", getattr(appointment, "doctor_id", None))
    new_start = update_data.get("start_time", appointment.start_time)
    new_end = update_data.get("end_time", appointment.end_time)

    provider = db.query(ProviderModel).filter(ProviderModel.id == new_provider_id).first()
    if not provider:
        raise HTTPException(status_code=400, detail="Provider does not exist")

    _validate_doctor_belongs_to_provider(db, new_provider_id, new_doctor_id)

    scope = _get_staff_scope(db, current_user)
    clinic_ids = scope["clinic_ids"]

    if clinic_ids:
        _ensure_provider_clinic_access(db, provider, current_user)
        _ensure_doctor_assignment_allowed(
            db,
            current_user=current_user,
            provider_id=new_provider_id,
            doctor_id=new_doctor_id,
        )
    else:
        my_provider = _get_my_provider_profile(db, current_user)
        if new_provider_id != my_provider.id:
            raise HTTPException(status_code=403, detail="Providers cannot change provider_id")

    if "episode_id" in update_data and update_data["episode_id"] is not None:
        _ensure_episode_access_for_provider(db, update_data["episode_id"], current_user)

    if "provider_id" in update_data:
        update_data["clinic_id"] = getattr(provider, "clinic_id", None)

    final_clinic_id = update_data.get("clinic_id", getattr(appointment, "clinic_id", None))
    if final_clinic_id:
        ensure_clinic_has_active_subscription(db, final_clinic_id)

    if (
        "start_time" in update_data
        or "end_time" in update_data
        or "doctor_id" in update_data
        or "provider_id" in update_data
    ):
        _ensure_no_appointment_conflict(
            db,
            provider_id=new_provider_id,
            doctor_id=new_doctor_id,
            start_time=new_start,
            end_time=new_end,
            ignore_appointment_id=appointment.id,
        )

    for field, value in update_data.items():
        setattr(appointment, field, value)

    db.commit()
    db.refresh(appointment)
    return _serialize_appointment(db, appointment)


@router.delete("/{appointment_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_appointment(
    appointment_id: int,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    if current_user.role in ("admin", "patient"):
        raise HTTPException(status_code=403, detail="Not enough permissions")

    appointment = db.query(AppointmentModel).filter(AppointmentModel.id == appointment_id).first()
    if not appointment:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Appointment not found")

    _ensure_appointment_access(db, appointment, current_user)

    db.delete(appointment)
    db.commit()
    return None