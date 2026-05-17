# Path: backend/app/api/v1/provider_availability.py

from datetime import datetime, timezone
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.core.security import get_current_user
from app.db import get_db
from app.models.clinic_membership import ClinicMembership
from app.models.provider import Provider
from app.models.provider_availability import ProviderAvailability
from app.models.provider_availability_exception import ProviderAvailabilityException
from app.models.provider_doctor import ProviderDoctor
from app.schemas.provider_availability import (
    ProviderAvailabilityCreate,
    ProviderAvailabilityExceptionCreate,
    ProviderAvailabilityExceptionDeleteOut,
    ProviderAvailabilityExceptionOut,
    ProviderAvailabilityOut,
)

router = APIRouter(prefix="/providers/me/availability", tags=["provider-availability"])


def _get_my_active_membership(db: Session, current_user) -> Optional[ClinicMembership]:
    return (
        db.query(ClinicMembership)
        .filter(
            ClinicMembership.user_id == current_user.id,
            ClinicMembership.is_active.is_(True),
        )
        .order_by(ClinicMembership.id.desc())
        .first()
    )


def _get_my_provider(db: Session, current_user) -> Provider:
    provider = (
        db.query(Provider)
        .filter(Provider.user_id == current_user.id)
        .first()
    )
    if provider:
        return provider

    membership = _get_my_active_membership(db, current_user)
    if membership:
        provider = (
            db.query(Provider)
            .filter(
                Provider.clinic_id == membership.clinic_id,
                Provider.is_active.is_(True),
            )
            .order_by(Provider.id.desc())
            .first()
        )
        if provider:
            return provider

    raise HTTPException(status_code=404, detail="Provider profile not found")


def _validate_my_doctor(
    db: Session,
    provider_id: int,
    doctor_id: Optional[int],
) -> Optional[ProviderDoctor]:
    if doctor_id is None:
        return None

    doctor = (
        db.query(ProviderDoctor)
        .filter(
            ProviderDoctor.id == doctor_id,
            ProviderDoctor.provider_id == provider_id,
            ProviderDoctor.is_active.is_(True),
        )
        .first()
    )
    if not doctor:
        raise HTTPException(status_code=404, detail="Doctor not found for this provider")

    return doctor


def _resolve_doctor_scope(
    db: Session,
    provider_id: int,
    requested_doctor_id: Optional[int],
    current_user,
) -> Optional[int]:
    membership = _get_my_active_membership(db, current_user)

    if membership and membership.provider_doctor_id is not None:
        own_doctor_id = membership.provider_doctor_id

        if requested_doctor_id is not None and requested_doctor_id != own_doctor_id:
            raise HTTPException(
                status_code=403,
                detail="Doctor users can manage only their own availability.",
            )

        _validate_my_doctor(db, provider_id, own_doctor_id)
        return own_doctor_id

    _validate_my_doctor(db, provider_id, requested_doctor_id)
    return requested_doctor_id


@router.get("", response_model=List[ProviderAvailabilityOut])
def list_my_availability(
    doctor_id: Optional[int] = Query(None),
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    provider = _get_my_provider(db, current_user)
    effective_doctor_id = _resolve_doctor_scope(
        db=db,
        provider_id=provider.id,
        requested_doctor_id=doctor_id,
        current_user=current_user,
    )

    query = db.query(ProviderAvailability).filter(
        ProviderAvailability.provider_id == provider.id
    )

    if effective_doctor_id is None:
        query = query.filter(ProviderAvailability.doctor_id.is_(None))
    else:
        query = query.filter(ProviderAvailability.doctor_id == effective_doctor_id)

    return query.order_by(ProviderAvailability.weekday.asc()).all()


@router.post("", response_model=ProviderAvailabilityOut)
def create_or_update_my_availability(
    payload: ProviderAvailabilityCreate,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    provider = _get_my_provider(db, current_user)
    effective_doctor_id = _resolve_doctor_scope(
        db=db,
        provider_id=provider.id,
        requested_doctor_id=payload.doctor_id,
        current_user=current_user,
    )

    row = (
        db.query(ProviderAvailability)
        .filter(
            ProviderAvailability.provider_id == provider.id,
            ProviderAvailability.doctor_id == effective_doctor_id,
            ProviderAvailability.weekday == payload.weekday,
        )
        .first()
    )

    if row:
        row.start_time = payload.start_time
        row.end_time = payload.end_time
        row.is_active = True
        db.commit()
        db.refresh(row)
        return row

    availability = ProviderAvailability(
        provider_id=provider.id,
        doctor_id=effective_doctor_id,
        weekday=payload.weekday,
        start_time=payload.start_time,
        end_time=payload.end_time,
        is_active=True,
    )

    db.add(availability)
    db.commit()
    db.refresh(availability)
    return availability


@router.delete("/{availability_id}")
def delete_my_availability(
    availability_id: int,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    provider = _get_my_provider(db, current_user)
    membership = _get_my_active_membership(db, current_user)

    query = db.query(ProviderAvailability).filter(
        ProviderAvailability.id == availability_id,
        ProviderAvailability.provider_id == provider.id,
    )

    if membership and membership.provider_doctor_id is not None:
        query = query.filter(
            ProviderAvailability.doctor_id == membership.provider_doctor_id
        )

    row = query.first()
    if not row:
        raise HTTPException(status_code=404, detail="Availability not found")

    db.delete(row)
    db.commit()

    return {
        "ok": True,
        "id": availability_id,
        "deleted_at": datetime.now(timezone.utc),
    }


@router.get("/exceptions", response_model=List[ProviderAvailabilityExceptionOut])
def list_exceptions(
    doctor_id: Optional[int] = Query(None),
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    provider = _get_my_provider(db, current_user)
    effective_doctor_id = _resolve_doctor_scope(
        db=db,
        provider_id=provider.id,
        requested_doctor_id=doctor_id,
        current_user=current_user,
    )

    query = db.query(ProviderAvailabilityException).filter(
        ProviderAvailabilityException.provider_id == provider.id
    )

    if effective_doctor_id is None:
        query = query.filter(ProviderAvailabilityException.doctor_id.is_(None))
    else:
        query = query.filter(
            ProviderAvailabilityException.doctor_id == effective_doctor_id
        )

    return query.order_by(ProviderAvailabilityException.date.asc()).all()


@router.post("/exceptions", response_model=ProviderAvailabilityExceptionOut)
def create_or_update_exception(
    payload: ProviderAvailabilityExceptionCreate,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    provider = _get_my_provider(db, current_user)
    effective_doctor_id = _resolve_doctor_scope(
        db=db,
        provider_id=provider.id,
        requested_doctor_id=payload.doctor_id,
        current_user=current_user,
    )

    if not payload.is_closed:
        if payload.start_time is None or payload.end_time is None:
            raise HTTPException(
                status_code=400,
                detail="Open exception requires start_time and end_time",
            )
        if payload.start_time >= payload.end_time:
            raise HTTPException(
                status_code=400,
                detail="start_time must be earlier than end_time",
            )

    row = (
        db.query(ProviderAvailabilityException)
        .filter(
            ProviderAvailabilityException.provider_id == provider.id,
            ProviderAvailabilityException.doctor_id == effective_doctor_id,
            ProviderAvailabilityException.date == payload.date,
        )
        .first()
    )

    if row:
        row.is_closed = payload.is_closed
        row.start_time = None if payload.is_closed else payload.start_time
        row.end_time = None if payload.is_closed else payload.end_time
        row.note = payload.note
        db.commit()
        db.refresh(row)
        return row

    exception = ProviderAvailabilityException(
        provider_id=provider.id,
        doctor_id=effective_doctor_id,
        date=payload.date,
        is_closed=payload.is_closed,
        start_time=None if payload.is_closed else payload.start_time,
        end_time=None if payload.is_closed else payload.end_time,
        note=payload.note,
    )

    db.add(exception)
    db.commit()
    db.refresh(exception)
    return exception


@router.delete(
    "/exceptions/{exception_id}",
    response_model=ProviderAvailabilityExceptionDeleteOut,
)
def delete_exception(
    exception_id: int,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    provider = _get_my_provider(db, current_user)
    membership = _get_my_active_membership(db, current_user)

    query = db.query(ProviderAvailabilityException).filter(
        ProviderAvailabilityException.id == exception_id,
        ProviderAvailabilityException.provider_id == provider.id,
    )

    if membership and membership.provider_doctor_id is not None:
        query = query.filter(
            ProviderAvailabilityException.doctor_id == membership.provider_doctor_id
        )

    row = query.first()
    if not row:
        raise HTTPException(status_code=404, detail="Exception not found")

    db.delete(row)
    db.commit()

    return {
        "ok": True,
        "id": exception_id,
        "deleted_at": datetime.now(timezone.utc),
    }