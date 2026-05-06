# Path: backend/app/services/subscriptions.py

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from app import models

DEFAULT_TRIAL_DAYS = 90
DEFAULT_TRIAL_PLAN_CODE = "trial-90"
DEFAULT_TRIAL_PLAN_NAME = "Free Trial 3 luni"


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def ensure_default_trial_plan(db: Session) -> models.SubscriptionPlan:
    """
    Ensures there is a default 90-day free trial plan in the database.
    Reuses existing plan by code when available.
    """
    plan = (
        db.query(models.SubscriptionPlan)
        .filter(models.SubscriptionPlan.code == DEFAULT_TRIAL_PLAN_CODE)
        .first()
    )
    if plan:
        updated = False

        if plan.name != DEFAULT_TRIAL_PLAN_NAME:
            plan.name = DEFAULT_TRIAL_PLAN_NAME
            updated = True

        if getattr(plan, "price_eur", None) != 0:
            plan.price_eur = 0
            updated = True

        if getattr(plan, "duration_days", None) != DEFAULT_TRIAL_DAYS:
            plan.duration_days = DEFAULT_TRIAL_DAYS
            updated = True

        if getattr(plan, "is_active", None) is not True:
            plan.is_active = True
            updated = True

        if updated:
            db.add(plan)
            db.flush()

        return plan

    plan = models.SubscriptionPlan(
        code=DEFAULT_TRIAL_PLAN_CODE,
        name=DEFAULT_TRIAL_PLAN_NAME,
        price_eur=0,
        duration_days=DEFAULT_TRIAL_DAYS,
        is_active=True,
    )
    db.add(plan)
    db.flush()
    return plan


def get_active_or_trial_subscription_for_clinic(
    db: Session,
    clinic_id: int,
) -> models.ClinicSubscription | None:
    """
    Returns an existing active/trialing subscription for the clinic if one exists.
    """
    now = utcnow()

    return (
        db.query(models.ClinicSubscription)
        .filter(models.ClinicSubscription.clinic_id == clinic_id)
        .filter(models.ClinicSubscription.status.in_(["trialing", "active"]))
        .filter(models.ClinicSubscription.ends_at >= now)
        .order_by(models.ClinicSubscription.ends_at.desc())
        .first()
    )


def ensure_clinic_trial_subscription(
    db: Session,
    clinic_id: int,
) -> models.ClinicSubscription:
    """
    Ensures the clinic has a valid trial subscription.
    If there is already an active/trialing subscription, it is reused.
    Otherwise, a new 90-day trial is created.
    """
    existing = get_active_or_trial_subscription_for_clinic(db, clinic_id)
    if existing:
        return existing

    plan = ensure_default_trial_plan(db)

    starts_at = utcnow()
    ends_at = starts_at + timedelta(days=DEFAULT_TRIAL_DAYS)

    subscription = models.ClinicSubscription(
        clinic_id=clinic_id,
        plan_id=plan.id,
        status="trialing",
        starts_at=starts_at,
        ends_at=ends_at,
    )
    db.add(subscription)
    db.flush()
    return subscription