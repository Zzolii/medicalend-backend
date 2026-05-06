# Path: backend/app/services/stripe_service.py

from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone

import stripe
from fastapi import HTTPException
from sqlalchemy.orm import Session

from app import models
from app.services.subscriptions import utcnow

STRIPE_SECRET_KEY = os.getenv("STRIPE_SECRET_KEY", "")
STRIPE_WEBHOOK_SECRET = os.getenv("STRIPE_WEBHOOK_SECRET", "")
FRONTEND_APP_URL = os.getenv("FRONTEND_APP_URL", "http://localhost:3000")

if STRIPE_SECRET_KEY:
    stripe.api_key = STRIPE_SECRET_KEY


def ensure_stripe_configured():
    if not STRIPE_SECRET_KEY:
        raise HTTPException(
            status_code=500,
            detail="Stripe is not configured. Missing STRIPE_SECRET_KEY.",
        )


def get_frontend_success_url() -> str:
    return f"{FRONTEND_APP_URL.rstrip('/')}/billing?checkout=success"


def get_frontend_cancel_url() -> str:
    return f"{FRONTEND_APP_URL.rstrip('/')}/billing?checkout=cancel"


def get_or_create_stripe_customer_for_clinic(
    db: Session,
    clinic: models.Clinic,
) -> str:
    """
    Reuses clinic.stripe_customer_id if present.
    If model field does not exist yet, Stripe customer is still created,
    but customer id will not be persisted unless the field exists.
    """
    ensure_stripe_configured()

    existing_customer_id = getattr(clinic, "stripe_customer_id", None)
    if existing_customer_id:
        return existing_customer_id

    customer = stripe.Customer.create(
        name=getattr(clinic, "name", None) or f"Clinic #{clinic.id}",
        email=getattr(clinic, "email", None),
        phone=getattr(clinic, "phone", None),
        metadata={
            "clinic_id": str(clinic.id),
        },
    )

    if hasattr(clinic, "stripe_customer_id"):
        clinic.stripe_customer_id = customer["id"]
        db.add(clinic)
        db.flush()

    return customer["id"]


def create_checkout_session_for_plan(
    db: Session,
    clinic: models.Clinic,
    plan: models.SubscriptionPlan,
) -> str:
    ensure_stripe_configured()

    if not getattr(plan, "is_active", False):
        raise HTTPException(status_code=400, detail="Selected plan is inactive.")

    if (getattr(plan, "price_eur", 0) or 0) <= 0:
        raise HTTPException(
            status_code=400,
            detail="Selected plan must have a price greater than 0 for Stripe checkout.",
        )

    customer_id = get_or_create_stripe_customer_for_clinic(db, clinic)

    amount_eur = float(getattr(plan, "price_eur", 0) or 0)
    amount_cents = int(round(amount_eur * 100))

    session = stripe.checkout.Session.create(
        mode="payment",
        customer=customer_id,
        success_url=get_frontend_success_url(),
        cancel_url=get_frontend_cancel_url(),
        payment_method_types=["card"],
        line_items=[
            {
                "quantity": 1,
                "price_data": {
                    "currency": "eur",
                    "unit_amount": amount_cents,
                    "product_data": {
                        "name": getattr(plan, "name", None) or f"Plan #{plan.id}",
                        "description": getattr(plan, "description", None)
                        or "MediCalend clinic subscription",
                    },
                },
            }
        ],
        metadata={
            "clinic_id": str(clinic.id),
            "plan_id": str(plan.id),
            "plan_code": getattr(plan, "code", None) or "",
        },
    )

    return session["url"]


def construct_stripe_event(payload: bytes, sig_header: str | None):
    ensure_stripe_configured()

    if not STRIPE_WEBHOOK_SECRET:
        raise HTTPException(
            status_code=500,
            detail="Stripe webhook secret is missing.",
        )

    try:
        return stripe.Webhook.construct_event(
            payload=payload,
            sig_header=sig_header,
            secret=STRIPE_WEBHOOK_SECRET,
        )
    except stripe.error.SignatureVerificationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


def activate_or_extend_subscription_after_payment(
    db: Session,
    clinic_id: int,
    plan_id: int,
):
    clinic = db.query(models.Clinic).filter(models.Clinic.id == clinic_id).first()
    if not clinic:
        raise HTTPException(status_code=404, detail="Clinic not found.")

    plan = (
        db.query(models.SubscriptionPlan)
        .filter(models.SubscriptionPlan.id == plan_id)
        .first()
    )
    if not plan:
        raise HTTPException(status_code=404, detail="Subscription plan not found.")

    duration_days = int(getattr(plan, "duration_days", 30) or 30)
    now = utcnow()

    latest = (
        db.query(models.ClinicSubscription)
        .filter(models.ClinicSubscription.clinic_id == clinic_id)
        .order_by(
            models.ClinicSubscription.ends_at.desc(),
            models.ClinicSubscription.id.desc(),
        )
        .first()
    )

    if latest and latest.status in ["active", "trialing"] and latest.ends_at >= now:
        start_from = latest.ends_at
        latest.plan_id = plan.id
        latest.status = "active"
        latest.ends_at = start_from + timedelta(days=duration_days)
        db.add(latest)
        db.flush()
        return latest

    subscription = models.ClinicSubscription(
        clinic_id=clinic_id,
        plan_id=plan.id,
        status="active",
        starts_at=now,
        ends_at=now + timedelta(days=duration_days),
    )
    db.add(subscription)
    db.flush()
    return subscription