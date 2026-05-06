# Path: backend/app/api/v1/provider_free_slots.py

from datetime import date, datetime, time, timedelta, timezone
from typing import Any, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.core.security import get_current_user
from app.db import get_db
from app.integrations.google_calendar.client import (
    integration_has_usable_tokens,
    query_freebusy,
)
from app.models.appointment import Appointment
from app.models.clinic_membership import ClinicMembership
from app.models.google_calendar_integration import GoogleCalendarIntegration
from app.models.provider import Provider
from app.models.provider_availability import ProviderAvailability
from app.models.provider_availability_exception import ProviderAvailabilityException
from app.models.provider_doctor import ProviderDoctor

router = APIRouter(prefix="/providers", tags=["provider-free-slots"])

SLOT_MINUTES = 30
DEFAULT_START_TIME = time(8, 0)
DEFAULT_END_TIME = time(16, 0)

STAFF_VIEW_ROLES = {"clinic_admin", "doctor", "assistant", "reception", "receptionist"}
BLOCKING_STATUSES = {"scheduled", "in_progress"}


def _normalize_clinic_role(value: Optional[str]) -> Optional[str]:
    if value == "receptionist":
        return "reception"
    return value


def _get_accessible_clinic_ids(db: Session, current_user) -> List[int]:
    memberships = (
        db.query(ClinicMembership)
        .filter(
            ClinicMembership.user_id == current_user.id,
            ClinicMembership.is_active == True,  # noqa: E712
        )
        .all()
    )

    clinic_ids: List[int] = []
    for membership in memberships:
        role = _normalize_clinic_role(getattr(membership, "role", None))
        if role in STAFF_VIEW_ROLES and membership.clinic_id not in clinic_ids:
            clinic_ids.append(membership.clinic_id)

    return clinic_ids


def _ensure_provider_access(db: Session, provider: Provider, current_user) -> None:
    if current_user.role in ("admin", "patient"):
        return

    clinic_ids = _get_accessible_clinic_ids(db, current_user)
    if clinic_ids:
        if getattr(provider, "clinic_id", None) not in clinic_ids:
            raise HTTPException(status_code=403, detail="Not allowed for this clinic")
        return

    if current_user.role == "provider":
        my_provider = db.query(Provider).filter(Provider.user_id == current_user.id).first()
        if not my_provider:
            raise HTTPException(status_code=404, detail="Provider profile not linked to this user")
        if my_provider.id != provider.id:
            raise HTTPException(status_code=403, detail="Not allowed for this provider")
        return

    raise HTTPException(status_code=403, detail="Not enough permissions")


def combine_date_time(d: date, t: time) -> datetime:
    return datetime(d.year, d.month, d.day, t.hour, t.minute, t.second)


def generate_base_slots(start_dt: datetime, end_dt: datetime) -> List[datetime]:
    slots: List[datetime] = []
    current = start_dt

    while current + timedelta(minutes=SLOT_MINUTES) <= end_dt:
        slots.append(current)
        current += timedelta(minutes=SLOT_MINUTES)

    return slots


def _default_work_window(date_value: date) -> Optional[tuple[datetime, datetime]]:
    if date_value.weekday() >= 5:
        return None

    return (
        combine_date_time(date_value, DEFAULT_START_TIME),
        combine_date_time(date_value, DEFAULT_END_TIME),
    )


def _resolve_provider_work_window(
    db: Session,
    provider_id: int,
    date_value: date,
) -> Optional[tuple[datetime, datetime]]:
    provider_exception = (
        db.query(ProviderAvailabilityException)
        .filter(
            ProviderAvailabilityException.provider_id == provider_id,
            ProviderAvailabilityException.doctor_id.is_(None),
            ProviderAvailabilityException.date == date_value,
        )
        .first()
    )

    if provider_exception:
        if provider_exception.is_closed:
            return None

        if provider_exception.start_time and provider_exception.end_time:
            return (
                combine_date_time(date_value, provider_exception.start_time),
                combine_date_time(date_value, provider_exception.end_time),
            )

        return None

    provider_availability = (
        db.query(ProviderAvailability)
        .filter(
            ProviderAvailability.provider_id == provider_id,
            ProviderAvailability.doctor_id.is_(None),
            ProviderAvailability.weekday == date_value.weekday(),
            ProviderAvailability.is_active == True,  # noqa: E712
        )
        .first()
    )

    if provider_availability:
        return (
            combine_date_time(date_value, provider_availability.start_time),
            combine_date_time(date_value, provider_availability.end_time),
        )

    return _default_work_window(date_value)


def resolve_work_window(
    db: Session,
    provider_id: int,
    date_value: date,
    doctor_id: Optional[int],
) -> Optional[tuple[datetime, datetime]]:
    if doctor_id is not None:
        doctor_exception = (
            db.query(ProviderAvailabilityException)
            .filter(
                ProviderAvailabilityException.provider_id == provider_id,
                ProviderAvailabilityException.doctor_id == doctor_id,
                ProviderAvailabilityException.date == date_value,
            )
            .first()
        )

        if doctor_exception:
            if doctor_exception.is_closed:
                return None

            if doctor_exception.start_time and doctor_exception.end_time:
                return (
                    combine_date_time(date_value, doctor_exception.start_time),
                    combine_date_time(date_value, doctor_exception.end_time),
                )

            return None

        doctor_availability = (
            db.query(ProviderAvailability)
            .filter(
                ProviderAvailability.provider_id == provider_id,
                ProviderAvailability.doctor_id == doctor_id,
                ProviderAvailability.weekday == date_value.weekday(),
                ProviderAvailability.is_active == True,  # noqa: E712
            )
            .first()
        )

        if doctor_availability:
            return (
                combine_date_time(date_value, doctor_availability.start_time),
                combine_date_time(date_value, doctor_availability.end_time),
            )

        return _resolve_provider_work_window(db, provider_id, date_value)

    return _resolve_provider_work_window(db, provider_id, date_value)


def _as_naive(dt: Optional[datetime]) -> Optional[datetime]:
    if dt is None:
        return None

    if dt.tzinfo is not None:
        return dt.astimezone(timezone.utc).replace(tzinfo=None)

    return dt


def _parse_google_dt(value: Any) -> Optional[datetime]:
    if value is None:
        return None

    if isinstance(value, datetime):
        return _as_naive(value)

    if isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
            return _as_naive(parsed)
        except ValueError:
            return None

    return None


def _appointment_end(appt: Appointment) -> Optional[datetime]:
    start_time = _as_naive(appt.start_time)
    end_time = _as_naive(appt.end_time)

    if start_time is None:
        return None

    if end_time is not None:
        return end_time

    return start_time + timedelta(minutes=SLOT_MINUTES)


def _slot_overlaps(
    slot_start: datetime,
    slot_end: datetime,
    appt_start: datetime,
    appt_end: datetime,
) -> bool:
    return slot_start < appt_end and appt_start < slot_end


def _has_contiguous_capacity(
    slot_start: datetime,
    duration: int,
    end_dt: datetime,
    blocked_starts: set[datetime],
) -> bool:
    slot_end = slot_start + timedelta(minutes=duration)
    if slot_end > end_dt:
        return False

    current = slot_start
    while current < slot_end:
        if current in blocked_starts:
            return False
        current += timedelta(minutes=SLOT_MINUTES)

    return True


def _get_google_calendar_mapping(
    db: Session,
    *,
    provider_id: int,
    doctor_id: Optional[int],
) -> Optional[GoogleCalendarIntegration]:
    if doctor_id is not None:
        doctor_mapping = (
            db.query(GoogleCalendarIntegration)
            .filter(
                GoogleCalendarIntegration.provider_id == provider_id,
                GoogleCalendarIntegration.doctor_id == doctor_id,
                GoogleCalendarIntegration.is_active == True,  # noqa: E712
                GoogleCalendarIntegration.status == "connected",
            )
            .order_by(GoogleCalendarIntegration.id.desc())
            .first()
        )
        if doctor_mapping and integration_has_usable_tokens(doctor_mapping):
            return doctor_mapping

    provider_mapping = (
        db.query(GoogleCalendarIntegration)
        .filter(
            GoogleCalendarIntegration.provider_id == provider_id,
            GoogleCalendarIntegration.doctor_id.is_(None),
            GoogleCalendarIntegration.is_active == True,  # noqa: E712
            GoogleCalendarIntegration.status == "connected",
        )
        .order_by(GoogleCalendarIntegration.id.desc())
        .first()
    )

    if provider_mapping and integration_has_usable_tokens(provider_mapping):
        return provider_mapping

    return None


def _add_google_busy_blocks(
    db: Session,
    *,
    provider_id: int,
    doctor_id: Optional[int],
    start_dt: datetime,
    end_dt: datetime,
    base_slots: List[datetime],
    blocked_starts: set[datetime],
) -> None:
    mapping = _get_google_calendar_mapping(
        db,
        provider_id=provider_id,
        doctor_id=doctor_id,
    )

    if not mapping:
        return

    try:
        busy_items = query_freebusy(
            mapping,
            time_min=start_dt,
            time_max=end_dt,
        )
    except Exception:
        return

    for item in busy_items:
        busy_start = _parse_google_dt(item.get("start"))
        busy_end = _parse_google_dt(item.get("end"))

        if busy_start is None or busy_end is None:
            continue

        for base_start in base_slots:
            base_end = base_start + timedelta(minutes=SLOT_MINUTES)
            if _slot_overlaps(base_start, base_end, busy_start, busy_end):
                blocked_starts.add(base_start)


@router.get("/{provider_id}/free-slots")
def get_free_slots(
    provider_id: int,
    date_str: date = Query(..., alias="date"),
    duration: int = Query(30, ge=30),
    doctor_id: Optional[int] = Query(None),
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    provider = db.query(Provider).filter(Provider.id == provider_id).first()
    if not provider:
        raise HTTPException(status_code=404, detail="Provider not found")

    _ensure_provider_access(db, provider, current_user)

    if doctor_id is not None:
        doctor = (
            db.query(ProviderDoctor)
            .filter(
                ProviderDoctor.id == doctor_id,
                ProviderDoctor.provider_id == provider_id,
                ProviderDoctor.is_active == True,  # noqa: E712
            )
            .first()
        )
        if not doctor:
            raise HTTPException(status_code=404, detail="Doctor not found for this provider")

    window = resolve_work_window(db, provider_id, date_str, doctor_id)
    if not window:
        return []

    start_dt, end_dt = window
    base_slots = generate_base_slots(start_dt, end_dt)

    if not base_slots:
        return []

    appointments_query = (
        db.query(Appointment)
        .filter(
            Appointment.provider_id == provider_id,
            Appointment.start_time < end_dt,
            Appointment.status.in_(BLOCKING_STATUSES),
        )
    )

    if doctor_id is not None:
        appointments_query = appointments_query.filter(Appointment.doctor_id == doctor_id)
    else:
        appointments_query = appointments_query.filter(Appointment.doctor_id.is_(None))

    appointments = appointments_query.all()

    blocked_starts: set[datetime] = set()

    for appt in appointments:
        appt_start = _as_naive(appt.start_time)
        appt_end = _appointment_end(appt)

        if appt_start is None or appt_end is None:
            continue

        for base_start in base_slots:
            base_end = base_start + timedelta(minutes=SLOT_MINUTES)
            if _slot_overlaps(base_start, base_end, appt_start, appt_end):
                blocked_starts.add(base_start)

    _add_google_busy_blocks(
        db,
        provider_id=provider_id,
        doctor_id=doctor_id,
        start_dt=start_dt,
        end_dt=end_dt,
        base_slots=base_slots,
        blocked_starts=blocked_starts,
    )

    result = []

    for slot_start in base_slots:
        slot_end = slot_start + timedelta(minutes=duration)

        available = _has_contiguous_capacity(
            slot_start=slot_start,
            duration=duration,
            end_dt=end_dt,
            blocked_starts=blocked_starts,
        )

        result.append(
            {
                "start_time": slot_start.isoformat(),
                "end_time": slot_end.isoformat(),
                "available": available,
            }
        )

    return result