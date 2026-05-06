# Path: backend/app/api/v1/providers.py

from datetime import date, datetime, time, timedelta, timezone
from typing import List, Optional
import unicodedata

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import or_
from sqlalchemy.orm import Session

from app import models
from app.core.security import (
    get_current_provider_for_user,
    get_current_user,
    require_roles,
)
from app.db import get_db
from app.models.appointment import Appointment as AppointmentModel
from app.models.provider_availability import ProviderAvailability
from app.models.provider_availability_exception import (
    ProviderAvailabilityException,
)
from app.models.provider_doctor import ProviderDoctor as ProviderDoctorModel
from app.models.provider_specialty import ProviderSpecialty as ProviderSpecialtyModel
from app.schemas.provider import (
    Provider,
    ProviderAvailabilitySlot,
    ProviderCreate,
    ProviderUpdate,
)

router = APIRouter(prefix="/providers", tags=["providers"])

SLOT_MINUTES = 30
EARLIEST_SEARCH_DAYS = 30


def _get_my_provider_profile(db: Session, current_user) -> models.Provider:
    return get_current_provider_for_user(db, current_user)


def _has_clinic_admin_membership(current_user) -> bool:
    memberships = getattr(current_user, "clinic_memberships", None) or []
    return any(
        getattr(membership, "is_active", False)
        and getattr(membership, "role", None) == "clinic_admin"
        for membership in memberships
    )


def _clean_str(value: Optional[str]) -> Optional[str]:
    if value is None:
        return None
    value = str(value).strip()
    return value or None


def _normalize_text(value: Optional[str]) -> str:
    raw = str(value or "").strip().lower()
    without_diacritics = unicodedata.normalize("NFD", raw)
    return "".join(
        char for char in without_diacritics if unicodedata.category(char) != "Mn"
    )


def _text_contains(haystack: Optional[str], needle: Optional[str]) -> bool:
    needle_norm = _normalize_text(needle)
    if not needle_norm:
        return True

    return needle_norm in _normalize_text(haystack)


def _provider_matches_normalized_filters(
    provider: models.Provider,
    *,
    city: Optional[str] = None,
    county: Optional[str] = None,
    service: Optional[str] = None,
    name: Optional[str] = None,
    coverage_area: Optional[str] = None,
) -> bool:
    if city and not _text_contains(getattr(provider, "city", None), city):
        return False

    if county and not _text_contains(getattr(provider, "county", None), county):
        return False

    if name and not _text_contains(getattr(provider, "name", None), name):
        return False

    if service:
        specialty_match = _text_contains(getattr(provider, "specialty", None), service)
        services_match = _text_contains(
            getattr(provider, "services_offered", None),
            service,
        )
        if not specialty_match and not services_match:
            return False

    if coverage_area and not _text_contains(
        getattr(provider, "coverage_area", None),
        coverage_area,
    ):
        return False

    return True


def _doctor_matches_normalized_filters(
    doctor: ProviderDoctorModel,
    provider: models.Provider,
    specialty: ProviderSpecialtyModel,
    *,
    doctor_name: Optional[str] = None,
    specialty_value: Optional[str] = None,
    provider_name: Optional[str] = None,
    city: Optional[str] = None,
    county: Optional[str] = None,
) -> bool:
    if doctor_name:
        doctor_name_match = _text_contains(getattr(doctor, "name", None), doctor_name)
        doctor_title_match = _text_contains(getattr(doctor, "title", None), doctor_name)
        if not doctor_name_match and not doctor_title_match:
            return False

    if specialty_value:
        doctor_specialty_match = _text_contains(
            getattr(specialty, "name", None),
            specialty_value,
        )
        provider_specialty_match = _text_contains(
            getattr(provider, "specialty", None),
            specialty_value,
        )
        provider_services_match = _text_contains(
            getattr(provider, "services_offered", None),
            specialty_value,
        )
        if (
            not doctor_specialty_match
            and not provider_specialty_match
            and not provider_services_match
        ):
            return False

    if provider_name and not _text_contains(getattr(provider, "name", None), provider_name):
        return False

    if city and not _text_contains(getattr(provider, "city", None), city):
        return False

    if county and not _text_contains(getattr(provider, "county", None), county):
        return False

    return True


def _normalize_provider_payload_dict(data: dict) -> dict:
    string_fields = [
        "name",
        "provider_type",
        "website",
        "image_url",
        "public_description",
        "specialty",
        "services_offered",
        "license_number",
        "cui",
        "trade_register_number",
        "contact_person_name",
        "contact_phone",
        "phone",
        "address_line",
        "city",
        "county",
        "postal_code",
        "country",
        "coverage_area",
        "sanitary_authorization_number",
        "fhir_id",
        "rejection_reason",
    ]

    email_fields = [
        "email",
        "contact_email",
    ]

    for field in string_fields:
        if field in data:
            data[field] = _clean_str(data[field])

    for field in email_fields:
        if field in data:
            data[field] = _clean_str(data[field])

    return data


def _combine_date_time(d: date, t: time) -> datetime:
    return datetime(d.year, d.month, d.day, t.hour, t.minute, t.second)


def _to_naive_utc(dt_value: Optional[datetime]) -> Optional[datetime]:
    if dt_value is None:
        return None

    if dt_value.tzinfo is None or dt_value.tzinfo.utcoffset(dt_value) is None:
        return dt_value.replace(tzinfo=None)

    return dt_value.astimezone(timezone.utc).replace(tzinfo=None)


def _generate_slots(
    start_dt: datetime,
    end_dt: datetime,
    minutes: int = SLOT_MINUTES,
) -> List[tuple[datetime, datetime]]:
    slots: List[tuple[datetime, datetime]] = []
    current = start_dt

    while current + timedelta(minutes=minutes) <= end_dt:
        slot_end = current + timedelta(minutes=minutes)
        slots.append((current, slot_end))
        current = slot_end

    return slots


def _resolve_work_window(
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
                    _combine_date_time(date_value, doctor_exception.start_time),
                    _combine_date_time(date_value, doctor_exception.end_time),
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
                _combine_date_time(date_value, doctor_availability.start_time),
                _combine_date_time(date_value, doctor_availability.end_time),
            )

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
                _combine_date_time(date_value, provider_exception.start_time),
                _combine_date_time(date_value, provider_exception.end_time),
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
            _combine_date_time(date_value, provider_availability.start_time),
            _combine_date_time(date_value, provider_availability.end_time),
        )

    return None


def _slot_overlaps_appointment(
    appointment_start: Optional[datetime],
    appointment_end: Optional[datetime],
    slot_start: datetime,
    slot_end: datetime,
) -> bool:
    start_dt = _to_naive_utc(appointment_start)
    end_dt = _to_naive_utc(appointment_end)

    if start_dt is None:
        return False

    if end_dt is None:
        end_dt = start_dt + timedelta(minutes=SLOT_MINUTES)

    return start_dt < slot_end and end_dt > slot_start


def _provider_has_slot_at(
    db: Session,
    provider_id: int,
    target_date: date,
    target_time: time,
    doctor_id: Optional[int] = None,
    duration_minutes: int = SLOT_MINUTES,
) -> bool:
    window = _resolve_work_window(db, provider_id, target_date, doctor_id)
    if not window:
        return False

    work_start, work_end = window
    slot_start = datetime.combine(target_date, target_time)
    slot_end = slot_start + timedelta(minutes=duration_minutes)

    if slot_start < work_start or slot_end > work_end:
        return False

    appointments_query = (
        db.query(AppointmentModel)
        .filter(
            AppointmentModel.provider_id == provider_id,
            AppointmentModel.status.in_(["scheduled", "in_progress"]),
        )
    )

    if doctor_id is None:
        appointments_query = appointments_query.filter(
            AppointmentModel.doctor_id.is_(None)
        )
    else:
        appointments_query = appointments_query.filter(
            AppointmentModel.doctor_id == doctor_id
        )

    appointments = appointments_query.all()

    for appointment in appointments:
        if _slot_overlaps_appointment(
            appointment.start_time,
            appointment.end_time,
            slot_start,
            slot_end,
        ):
            return False

    return True


def _find_earliest_available_slot(
    db: Session,
    provider_id: int,
    doctor_id: Optional[int],
    start_from_date: Optional[date] = None,
    days_ahead: int = EARLIEST_SEARCH_DAYS,
) -> Optional[datetime]:
    base_date = start_from_date or date.today()

    for offset in range(days_ahead):
        day = base_date + timedelta(days=offset)
        window = _resolve_work_window(db, provider_id, day, doctor_id)

        if not window:
            continue

        work_start, work_end = window
        slots = _generate_slots(work_start, work_end, SLOT_MINUTES)

        if not slots:
            continue

        appointments_query = (
            db.query(AppointmentModel)
            .filter(
                AppointmentModel.provider_id == provider_id,
                AppointmentModel.status.in_(["scheduled", "in_progress"]),
            )
        )

        if doctor_id is None:
            appointments_query = appointments_query.filter(
                AppointmentModel.doctor_id.is_(None)
            )
        else:
            appointments_query = appointments_query.filter(
                AppointmentModel.doctor_id == doctor_id
            )

        appointments = appointments_query.all()

        for slot_start, slot_end in slots:
            has_conflict = False

            for appointment in appointments:
                if _slot_overlaps_appointment(
                    appointment.start_time,
                    appointment.end_time,
                    slot_start,
                    slot_end,
                ):
                    has_conflict = True
                    break

            if not has_conflict:
                return slot_start

    return None


def _approved_active_provider_query(db: Session):
    return (
        db.query(models.Provider)
        .filter(models.Provider.status == "approved")
        .filter(models.Provider.is_active == True)  # noqa: E712
    )


def _filter_rows_by_slot(
    db: Session,
    rows: List[models.Provider],
    *,
    available_date: Optional[date],
    available_time: Optional[time],
    doctor_id: Optional[int],
) -> List[models.Provider]:
    # FONTOS:
    # Ezt már nem használjuk a publikus search endpointokban kizáró szűrésként,
    # mert patient oldalon félrevezető volt: ha specialty + időpont alapján keresett,
    # és az exact slot foglalt volt, minden találat eltűnt.
    # Meghagyjuk kompatibilitás miatt, de a search-clinics/search-homecare/search-doctors
    # már nem ezzel dobja ki a találatokat.
    if not available_date or not available_time:
        return rows

    return [
        provider
        for provider in rows
        if _provider_has_slot_at(
            db=db,
            provider_id=provider.id,
            target_date=available_date,
            target_time=available_time,
            doctor_id=doctor_id,
        )
    ]


def _get_public_provider_or_404(provider_id: int, db: Session) -> models.Provider:
    provider = db.query(models.Provider).filter(models.Provider.id == provider_id).first()
    if not provider:
        raise HTTPException(status_code=404, detail="Provider not found")

    if getattr(provider, "status", None) != "approved":
        raise HTTPException(status_code=404, detail="Provider not found")

    if getattr(provider, "is_active", True) is False:
        raise HTTPException(status_code=404, detail="Provider not found")

    return provider


@router.get(
    "/{provider_id}/availability",
    response_model=List[ProviderAvailabilitySlot],
)
def get_provider_availability(
    provider_id: int,
    date_value: date = Query(..., alias="date"),
    doctor_id: Optional[int] = Query(None),
    db: Session = Depends(get_db),
    _current_user=Depends(get_current_user),
):
    provider = _get_public_provider_or_404(provider_id, db)

    if doctor_id is not None:
        doctor = (
            db.query(ProviderDoctorModel)
            .filter(
                ProviderDoctorModel.id == doctor_id,
                ProviderDoctorModel.provider_id == provider.id,
                ProviderDoctorModel.is_active == True,  # noqa: E712
            )
            .first()
        )
        if not doctor:
            raise HTTPException(
                status_code=404,
                detail="Doctor not found for this provider",
            )

    window = _resolve_work_window(db, provider.id, date_value, doctor_id)
    if not window:
        return []

    work_start, work_end = window
    base_slots = _generate_slots(work_start, work_end, SLOT_MINUTES)

    appointments_query = (
        db.query(AppointmentModel)
        .filter(
            AppointmentModel.provider_id == provider.id,
            AppointmentModel.status.in_(["scheduled", "in_progress"]),
        )
    )

    if doctor_id is None:
        appointments_query = appointments_query.filter(
            AppointmentModel.doctor_id.is_(None)
        )
    else:
        appointments_query = appointments_query.filter(
            AppointmentModel.doctor_id == doctor_id
        )

    appointments = appointments_query.all()

    result: List[ProviderAvailabilitySlot] = []
    for start_dt, end_dt in base_slots:
        is_available = True

        for appointment in appointments:
            if _slot_overlaps_appointment(
                appointment.start_time,
                appointment.end_time,
                start_dt,
                end_dt,
            ):
                is_available = False
                break

        result.append(
            ProviderAvailabilitySlot(
                start_time=start_dt,
                end_time=end_dt,
                available=is_available,
            )
        )

    return result


@router.get("/search", response_model=List[Provider])
def search_providers(
    provider_type: Optional[str] = Query(None),
    city: Optional[str] = Query(None),
    county: Optional[str] = Query(None),
    service: Optional[str] = Query(None),
    name: Optional[str] = Query(None),
    coverage_area: Optional[str] = Query(None),
    available_date: Optional[date] = Query(None),
    available_time: Optional[time] = Query(None),
    doctor_id: Optional[int] = Query(None),
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=200),
    db: Session = Depends(get_db),
):
    provider_type = _clean_str(provider_type)

    query = _approved_active_provider_query(db)

    if provider_type == "clinic":
        query = query.filter(
            or_(
                models.Provider.provider_type == "clinic",
                models.Provider.provider_type.is_(None),
            )
        )
    elif provider_type == "home_care":
        query = query.filter(models.Provider.provider_type == "home_care")

    rows = query.order_by(models.Provider.id.desc()).offset(skip).limit(500).all()

    rows = [
        provider
        for provider in rows
        if _provider_matches_normalized_filters(
            provider,
            city=city,
            county=county,
            service=service,
            name=name,
            coverage_area=coverage_area if provider_type == "home_care" else None,
        )
    ]

    # Search fix:
    # Nem dobjuk ki a providert, ha az adott requested slot nem szabad.
    # A pontos szabad/foglalt státuszt a frontend a provider detail availability alapján
    # vagy doctor search esetén a has_requested_slot mezőből tudja megjeleníteni.
    # Provider response_model miatt itt nem adunk extra mezőt, hogy a régi Provider schema ne törjön.

    return rows[:limit]


@router.get("/search-clinics", response_model=List[Provider])
def search_clinics(
    city: Optional[str] = Query(None),
    county: Optional[str] = Query(None),
    specialty: Optional[str] = Query(None),
    name: Optional[str] = Query(None),
    available_date: Optional[date] = Query(None),
    available_time: Optional[time] = Query(None),
    doctor_id: Optional[int] = Query(None),
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=200),
    db: Session = Depends(get_db),
):
    query = _approved_active_provider_query(db).filter(
        or_(
            models.Provider.provider_type == "clinic",
            models.Provider.provider_type.is_(None),
        )
    )

    rows = query.order_by(models.Provider.id.desc()).offset(skip).limit(500).all()

    rows = [
        provider
        for provider in rows
        if _provider_matches_normalized_filters(
            provider,
            city=city,
            county=county,
            service=specialty,
            name=name,
        )
    ]

    # Search fix:
    # Nem szűrünk ki exact slot alapján, mert a beteg keresésénél így eltűntek
    # a releváns klinikák/orvosok. A foglalható időpontot a provider detail
    # availability endpoint mutatja ki pontosan.

    return rows[:limit]


@router.get("/search-homecare", response_model=List[Provider])
def search_homecare(
    city: Optional[str] = Query(None),
    county: Optional[str] = Query(None),
    service: Optional[str] = Query(None),
    name: Optional[str] = Query(None),
    coverage_area: Optional[str] = Query(None),
    available_date: Optional[date] = Query(None),
    available_time: Optional[time] = Query(None),
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=200),
    db: Session = Depends(get_db),
):
    query = _approved_active_provider_query(db).filter(
        models.Provider.provider_type == "home_care"
    )

    rows = query.order_by(models.Provider.id.desc()).offset(skip).limit(500).all()

    rows = [
        provider
        for provider in rows
        if _provider_matches_normalized_filters(
            provider,
            city=city,
            county=county,
            service=service,
            name=name,
            coverage_area=coverage_area,
        )
    ]

    # Search fix:
    # Domiciliu fülön sem dobjuk el a találatot csak azért,
    # mert az exact requested slot nem szabad/nincs konfigurálva.

    return rows[:limit]


@router.get("/search-doctors")
def search_doctors(
    doctor_name: Optional[str] = Query(None),
    specialty: Optional[str] = Query(None),
    provider_name: Optional[str] = Query(None),
    city: Optional[str] = Query(None),
    county: Optional[str] = Query(None),
    available_date: Optional[date] = Query(None),
    available_time: Optional[time] = Query(None),
    limit: int = Query(100, ge=1, le=200),
    db: Session = Depends(get_db),
):
    doctor_name = _clean_str(doctor_name)
    specialty = _clean_str(specialty)
    provider_name = _clean_str(provider_name)
    city = _clean_str(city)
    county = _clean_str(county)

    query = (
        db.query(ProviderDoctorModel, models.Provider, ProviderSpecialtyModel)
        .join(models.Provider, ProviderDoctorModel.provider_id == models.Provider.id)
        .join(
            ProviderSpecialtyModel,
            ProviderDoctorModel.specialty_id == ProviderSpecialtyModel.id,
        )
        .filter(ProviderDoctorModel.is_active == True)  # noqa: E712
        .filter(ProviderSpecialtyModel.is_active == True)  # noqa: E712
        .filter(models.Provider.status == "approved")
        .filter(models.Provider.is_active == True)  # noqa: E712
    )

    rows = (
        query.order_by(
            ProviderDoctorModel.name.asc(),
            models.Provider.name.asc(),
            ProviderDoctorModel.id.asc(),
        )
        .limit(500)
        .all()
    )

    result = []

    for doctor, provider, provider_specialty in rows:
        if not _doctor_matches_normalized_filters(
            doctor,
            provider,
            provider_specialty,
            doctor_name=doctor_name,
            specialty_value=specialty,
            provider_name=provider_name,
            city=city,
            county=county,
        ):
            continue

        has_requested_slot = None
        if available_date and available_time:
            has_requested_slot = _provider_has_slot_at(
                db=db,
                provider_id=provider.id,
                target_date=available_date,
                target_time=available_time,
                doctor_id=doctor.id,
            )

            # Search fix:
            # Régen itt "continue" volt, ezért ha nem volt pontosan szabad az adott slot,
            # eltűnt az orvos a találatokból. Most megtartjuk a találatot, és a frontend
            # a has_requested_slot=False alapján ki tudja írni, hogy az adott időpont nem szabad.

        earliest_available_at = _find_earliest_available_slot(
            db=db,
            provider_id=provider.id,
            doctor_id=doctor.id,
            start_from_date=available_date or date.today(),
            days_ahead=EARLIEST_SEARCH_DAYS,
        )

        result.append(
            {
                "doctor_id": doctor.id,
                "doctor_name": doctor.name,
                "doctor_title": doctor.title,
                "specialty_id": provider_specialty.id,
                "specialty_name": provider_specialty.name,
                "provider_id": provider.id,
                "provider_name": provider.name,
                "provider_type": provider.provider_type,
                "provider_image_url": getattr(provider, "image_url", None),
                "provider_website": getattr(provider, "website", None),
                "provider_public_description": getattr(
                    provider,
                    "public_description",
                    None,
                ),
                "city": provider.city,
                "county": provider.county,
                "address_line": provider.address_line,
                "phone": provider.phone,
                "email": provider.email,
                "has_requested_slot": has_requested_slot,
                "earliest_available_at": earliest_available_at.isoformat()
                if earliest_available_at
                else None,
            }
        )

        if len(result) >= limit:
            break

    return result


@router.get("/me", response_model=Provider)
def read_my_provider_profile(
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    if current_user.role not in ("provider", "admin") and not _has_clinic_admin_membership(current_user):
        raise HTTPException(status_code=403, detail="Not enough permissions")

    provider = _get_my_provider_profile(db, current_user)
    return provider


@router.delete("/me", status_code=status.HTTP_200_OK)
def delete_my_provider_profile(
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    if current_user.role not in ("provider", "admin") and not _has_clinic_admin_membership(current_user):
        raise HTTPException(status_code=403, detail="Not enough permissions")

    provider = _get_my_provider_profile(db, current_user)

    if getattr(provider, "is_active", True) is False:
        return {
            "ok": True,
            "provider_id": provider.id,
            "message": "Provider profile already deactivated.",
        }

    provider.is_active = False

    if hasattr(provider, "status"):
        provider.status = "rejected"

    if hasattr(provider, "rejection_reason"):
        provider.rejection_reason = "Account deleted by provider."

    if hasattr(current_user, "is_active"):
        current_user.is_active = False
        db.add(current_user)

    db.add(provider)
    db.commit()

    return {
        "ok": True,
        "provider_id": provider.id,
        "message": "Provider profile deactivated successfully.",
    }


@router.get("/{provider_id}/doctors")
def list_provider_doctors(
    provider_id: int,
    specialty_id: Optional[int] = Query(None),
    db: Session = Depends(get_db),
):
    provider = _get_public_provider_or_404(provider_id, db)

    query = (
        db.query(ProviderDoctorModel)
        .filter(
            ProviderDoctorModel.provider_id == provider.id,
            ProviderDoctorModel.is_active == True,  # noqa: E712
        )
    )

    if specialty_id is not None:
        query = query.filter(ProviderDoctorModel.specialty_id == specialty_id)

    doctors = query.order_by(ProviderDoctorModel.name.asc()).all()

    result = []
    for doctor in doctors:
        specialty_name = None
        if doctor.specialty is not None:
            specialty_name = getattr(doctor.specialty, "name", None)

        result.append(
            {
                "id": doctor.id,
                "provider_id": doctor.provider_id,
                "specialty_id": doctor.specialty_id,
                "name": doctor.name,
                "title": doctor.title,
                "license_number": doctor.license_number,
                "phone": doctor.phone,
                "email": doctor.email,
                "is_active": doctor.is_active,
                "created_at": doctor.created_at,
                "specialty_name": specialty_name,
            }
        )

    return result


@router.get("/{provider_id}", response_model=Provider)
def get_provider(provider_id: int, db: Session = Depends(get_db)):
    provider = _get_public_provider_or_404(provider_id, db)
    return provider


@router.get(
    "/",
    response_model=List[Provider],
    dependencies=[Depends(require_roles("admin", "provider"))],
)
def list_providers(skip: int = 0, limit: int = 100, db: Session = Depends(get_db)):
    return db.query(models.Provider).offset(skip).limit(limit).all()


@router.post(
    "/",
    response_model=Provider,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_roles("admin"))],
)
def create_provider(payload: ProviderCreate, db: Session = Depends(get_db)):
    if payload.cui:
        existing_cui = (
            db.query(models.Provider).filter(models.Provider.cui == payload.cui).first()
        )
        if existing_cui:
            raise HTTPException(status_code=409, detail="CUI already registered")

    if payload.trade_register_number:
        existing_trade_register = (
            db.query(models.Provider)
            .filter(
                models.Provider.trade_register_number == payload.trade_register_number
            )
            .first()
        )
        if existing_trade_register:
            raise HTTPException(
                status_code=409,
                detail="Trade register number already registered",
            )

    data = _normalize_provider_payload_dict(payload.model_dump())
    provider = models.Provider(**data)

    db.add(provider)
    db.commit()
    db.refresh(provider)
    return provider


@router.put(
    "/{provider_id}",
    response_model=Provider,
)
def update_provider(
    provider_id: int,
    payload: ProviderUpdate,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    provider = db.query(models.Provider).filter(models.Provider.id == provider_id).first()
    if not provider:
        raise HTTPException(status_code=404, detail="Provider not found")

    if current_user.role == "admin":
        data = payload.model_dump(exclude_unset=True)
    elif current_user.role == "provider" or _has_clinic_admin_membership(current_user):
        my_provider = _get_my_provider_profile(db, current_user)

        if provider.id != my_provider.id:
            raise HTTPException(
                status_code=403,
                detail="You can only update your own clinic provider profile",
            )

        data = payload.model_dump(exclude_unset=True)

        forbidden_for_non_admin = {"user_id", "status", "rejection_reason", "clinic_id"}
        for key in forbidden_for_non_admin:
            data.pop(key, None)
    else:
        raise HTTPException(status_code=403, detail="Not enough permissions")

    data = _normalize_provider_payload_dict(data)

    if "cui" in data and data["cui"]:
        existing_cui = (
            db.query(models.Provider)
            .filter(
                models.Provider.cui == data["cui"],
                models.Provider.id != provider.id,
            )
            .first()
        )
        if existing_cui:
            raise HTTPException(status_code=409, detail="CUI already registered")

    if "trade_register_number" in data and data["trade_register_number"]:
        existing_trade_register = (
            db.query(models.Provider)
            .filter(
                models.Provider.trade_register_number == data["trade_register_number"],
                models.Provider.id != provider.id,
            )
            .first()
        )
        if existing_trade_register:
            raise HTTPException(
                status_code=409,
                detail="Trade register number already registered",
            )

    for k, v in data.items():
        setattr(provider, k, v)

    db.commit()
    db.refresh(provider)
    return provider