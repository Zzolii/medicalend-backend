# Path: backend/app/api/v1/provider_availability.py

from datetime import datetime, timezone
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.core.security import get_current_user
from app.db import get_db
from app.models.provider import Provider
from app.models.provider_doctor import ProviderDoctor
from app.models.provider_availability import ProviderAvailability
from app.models.provider_availability_exception import ProviderAvailabilityException
from app.schemas.provider_availability import (
    ProviderAvailabilityCreate,
    ProviderAvailabilityOut,
    ProviderAvailabilityExceptionCreate,
    ProviderAvailabilityExceptionOut,
    ProviderAvailabilityExceptionDeleteOut,
)

router = APIRouter(prefix="/providers/me/availability", tags=["provider-availability"])


def _get_my_provider(db: Session, current_user):
    provider = db.query(Provider).filter(Provider.user_id == current_user.id).first()
    if not provider:
        raise HTTPException(status_code=404, detail="Provider profile not found")
    return provider


def _validate_my_doctor(db: Session, provider_id: int, doctor_id: Optional[int]):
    if doctor_id is None:
        return None

    doctor = (
        db.query(ProviderDoctor)
        .filter(
            ProviderDoctor.id == doctor_id,
            ProviderDoctor.provider_id == provider_id,
        )
        .first()
    )
    if not doctor:
        raise HTTPException(status_code=404, detail="Doctor not found for this provider")
    return doctor


@router.get("", response_model=List[ProviderAvailabilityOut])
def list_my_availability(
    doctor_id: Optional[int] = Query(None),
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    provider = _get_my_provider(db, current_user)
    _validate_my_doctor(db, provider.id, doctor_id)

    query = db.query(ProviderAvailability).filter(
        ProviderAvailability.provider_id == provider.id
    )

    if doctor_id is None:
        query = query.filter(ProviderAvailability.doctor_id.is_(None))
    else:
        query = query.filter(ProviderAvailability.doctor_id == doctor_id)

    return query.order_by(ProviderAvailability.weekday.asc()).all()


@router.post("", response_model=ProviderAvailabilityOut)
def create_or_update_my_availability(
    payload: ProviderAvailabilityCreate,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    provider = _get_my_provider(db, current_user)
    _validate_my_doctor(db, provider.id, payload.doctor_id)

    row = (
        db.query(ProviderAvailability)
        .filter(
            ProviderAvailability.provider_id == provider.id,
            ProviderAvailability.doctor_id == payload.doctor_id,
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
        doctor_id=payload.doctor_id,
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

    row = (
        db.query(ProviderAvailability)
        .filter(
            ProviderAvailability.id == availability_id,
            ProviderAvailability.provider_id == provider.id,
        )
        .first()
    )
    if not row:
        raise HTTPException(status_code=404, detail="Availability not found")

    db.delete(row)
    db.commit()
    return {"ok": True, "id": availability_id}


@router.get("/exceptions", response_model=List[ProviderAvailabilityExceptionOut])
def list_exceptions(
    doctor_id: Optional[int] = Query(None),
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    provider = _get_my_provider(db, current_user)
    _validate_my_doctor(db, provider.id, doctor_id)

    query = db.query(ProviderAvailabilityException).filter(
        ProviderAvailabilityException.provider_id == provider.id
    )

    if doctor_id is None:
        query = query.filter(ProviderAvailabilityException.doctor_id.is_(None))
    else:
        query = query.filter(ProviderAvailabilityException.doctor_id == doctor_id)

    return query.order_by(ProviderAvailabilityException.date.asc()).all()


@router.post("/exceptions", response_model=ProviderAvailabilityExceptionOut)
def create_or_update_exception(
    payload: ProviderAvailabilityExceptionCreate,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    provider = _get_my_provider(db, current_user)
    _validate_my_doctor(db, provider.id, payload.doctor_id)

    print("=== EXCEPTION PAYLOAD START ===")
    print("doctor_id:", payload.doctor_id)
    print("date:", payload.date)
    print("is_closed:", payload.is_closed)
    print("start_time:", payload.start_time)
    print("end_time:", payload.end_time)
    print("note:", payload.note)
    print("=== EXCEPTION PAYLOAD END ===")

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
            ProviderAvailabilityException.doctor_id == payload.doctor_id,
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
        doctor_id=payload.doctor_id,
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

    row = (
        db.query(ProviderAvailabilityException)
        .filter(
            ProviderAvailabilityException.id == exception_id,
            ProviderAvailabilityException.provider_id == provider.id,
        )
        .first()
    )
    if not row:
        raise HTTPException(status_code=404, detail="Exception not found")

    db.delete(row)
    db.commit()
    return {
        "ok": True,
        "id": exception_id,
        "deleted_at": datetime.now(timezone.utc),
    }