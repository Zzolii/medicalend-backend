# Path: backend/app/core/subscription.py

from datetime import datetime, timezone

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app import models


def _as_utc_aware(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def get_active_clinic_subscription(db: Session, clinic_id: int):
    return (
        db.query(models.ClinicSubscription)
        .filter(
            models.ClinicSubscription.clinic_id == clinic_id,
            models.ClinicSubscription.status.in_(["trialing", "active"]),
        )
        .order_by(models.ClinicSubscription.ends_at.desc())
        .first()
    )


def ensure_clinic_has_active_subscription(db: Session, clinic_id: int):
    sub = get_active_clinic_subscription(db, clinic_id)

    if not sub:
        raise HTTPException(
            status_code=402,
            detail="Subscription required",
        )

    now = datetime.now(timezone.utc)
    ends_at = _as_utc_aware(sub.ends_at)

    if ends_at is None or ends_at < now:
        sub.status = "expired"
        db.commit()

        raise HTTPException(
            status_code=402,
            detail="Subscription expired",
        )

    return sub