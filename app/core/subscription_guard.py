# Path: backend/app/core/subscription_guard.py

from __future__ import annotations

from datetime import datetime, timezone

from fastapi import Depends, HTTPException
from sqlalchemy.orm import Session

from app import models
from app.core.security import get_current_user
from app.db import get_db


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _as_utc_aware(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def resolve_clinic_id_for_user(db: Session, user: models.User) -> int | None:
    membership = (
        db.query(models.ClinicMembership)
        .filter(models.ClinicMembership.user_id == user.id)
        .filter(models.ClinicMembership.is_active.is_(True))
        .order_by(models.ClinicMembership.id.desc())
        .first()
    )
    if membership and membership.clinic_id:
        return membership.clinic_id

    provider = (
        db.query(models.Provider)
        .filter(models.Provider.user_id == user.id)
        .order_by(models.Provider.id.desc())
        .first()
    )
    if provider and getattr(provider, "clinic_id", None):
        return provider.clinic_id

    return None


def get_latest_clinic_subscription(
    db: Session,
    clinic_id: int,
) -> models.ClinicSubscription | None:
    return (
        db.query(models.ClinicSubscription)
        .filter(models.ClinicSubscription.clinic_id == clinic_id)
        .order_by(
            models.ClinicSubscription.ends_at.desc(),
            models.ClinicSubscription.id.desc(),
        )
        .first()
    )


def require_active_subscription_for_clinic(db: Session, clinic_id: int):
    subscription = get_latest_clinic_subscription(db, clinic_id)
    if not subscription:
        raise HTTPException(
            status_code=402,
            detail="Abonamentul clinicii nu este activ. Nu există subscription asociat.",
        )

    if subscription.status not in ["trialing", "active"]:
        raise HTTPException(
            status_code=402,
            detail="Abonamentul clinicii nu este activ.",
        )

    ends_at = _as_utc_aware(subscription.ends_at)
    if ends_at is None or ends_at < utcnow():
        raise HTTPException(
            status_code=402,
            detail="Abonamentul clinicii a expirat.",
        )

    return subscription


def require_active_subscription_for_current_user(
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    clinic_id = resolve_clinic_id_for_user(db, current_user)
    if not clinic_id:
        raise HTTPException(
            status_code=403,
            detail="Contul curent nu este asociat unei clinici.",
        )

    return require_active_subscription_for_clinic(db, clinic_id)