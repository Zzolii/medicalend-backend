# Path: backend/app/api/v1/subscriptions.py

from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app import models
from app.core.security import get_current_user
from app.db import get_db
from app.schemas.subscription import MyClinicSubscriptionOut

router = APIRouter(prefix="/subscriptions", tags=["subscriptions"])


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _resolve_clinic_id_for_user(db: Session, user: models.User) -> int | None:
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


@router.get("/me", response_model=MyClinicSubscriptionOut)
def get_my_clinic_subscription(
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    clinic_id = _resolve_clinic_id_for_user(db, current_user)
    if not clinic_id:
        raise HTTPException(
            status_code=404,
            detail="No clinic subscription is associated with this account.",
        )

    subscription = (
        db.query(models.ClinicSubscription)
        .filter(models.ClinicSubscription.clinic_id == clinic_id)
        .order_by(models.ClinicSubscription.ends_at.desc(), models.ClinicSubscription.id.desc())
        .first()
    )
    if not subscription:
        raise HTTPException(
            status_code=404,
            detail="No subscription found for this clinic.",
        )

    clinic = (
        db.query(models.Clinic)
        .filter(models.Clinic.id == subscription.clinic_id)
        .first()
    )
    plan = (
        db.query(models.SubscriptionPlan)
        .filter(models.SubscriptionPlan.id == subscription.plan_id)
        .first()
    )

    return MyClinicSubscriptionOut(
        id=subscription.id,
        clinic_id=subscription.clinic_id,
        clinic_name=getattr(clinic, "name", None) if clinic else None,
        plan_id=subscription.plan_id,
        plan_code=getattr(plan, "code", None) if plan else None,
        plan_name=getattr(plan, "name", None) if plan else None,
        price_eur=getattr(plan, "price_eur", None) if plan else None,
        duration_days=getattr(plan, "duration_days", None) if plan else None,
        status=subscription.status,
        starts_at=subscription.starts_at,
        ends_at=subscription.ends_at,
        created_at=getattr(subscription, "created_at", None),
    )