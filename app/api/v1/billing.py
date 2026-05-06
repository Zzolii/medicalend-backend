# Path: backend/app/api/v1/billing.py

from __future__ import annotations

import stripe
from fastapi import APIRouter, Depends, Header, HTTPException, Request
from sqlalchemy.orm import Session

from app import models
from app.core.security import get_current_user
from app.db import get_db
from app.schemas.billing import (
    BillingPortalOut,
    CreateCheckoutSessionIn,
    CreateCheckoutSessionOut,
)
from app.services.stripe_service import (
    STRIPE_SECRET_KEY,
    activate_or_extend_subscription_after_payment,
    construct_stripe_event,
    create_checkout_session_for_plan,
    get_frontend_success_url,
    get_or_create_stripe_customer_for_clinic,
)

router = APIRouter(prefix="/billing", tags=["billing"])


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


def _stripe_object_to_dict(value) -> dict:
    """
    Stripe may return StripeObject instances instead of plain dict.
    Convert safely to a normal dict so `.get(...)` works reliably.
    """
    if value is None:
        return {}

    if isinstance(value, dict):
        return value

    # Stripe objects expose to_dict_recursive in current SDKs
    to_dict_recursive = getattr(value, "to_dict_recursive", None)
    if callable(to_dict_recursive):
        result = to_dict_recursive()
        if isinstance(result, dict):
            return result

    # Fallback for mapping-like values
    try:
        return dict(value)
    except Exception:
        return {}


@router.post(
    "/checkout-session",
    response_model=CreateCheckoutSessionOut,
)
def create_checkout_session(
    payload: CreateCheckoutSessionIn,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    clinic_id = _resolve_clinic_id_for_user(db, current_user)
    if not clinic_id:
        raise HTTPException(
            status_code=403,
            detail="Current account is not associated with a clinic.",
        )

    clinic = db.query(models.Clinic).filter(models.Clinic.id == clinic_id).first()
    if not clinic:
        raise HTTPException(status_code=404, detail="Clinic not found.")

    plan = (
        db.query(models.SubscriptionPlan)
        .filter(models.SubscriptionPlan.id == payload.plan_id)
        .first()
    )
    if not plan:
        raise HTTPException(status_code=404, detail="Subscription plan not found.")

    checkout_url = create_checkout_session_for_plan(db, clinic, plan)
    db.commit()

    return CreateCheckoutSessionOut(checkout_url=checkout_url)


@router.post("/webhook/stripe")
async def stripe_webhook(
    request: Request,
    stripe_signature: str | None = Header(default=None, alias="Stripe-Signature"),
    db: Session = Depends(get_db),
):
    payload = await request.body()
    event = construct_stripe_event(payload=payload, sig_header=stripe_signature)

    event_type = event["type"]

    if event_type == "checkout.session.completed":
        session = event["data"]["object"]
        metadata = _stripe_object_to_dict(getattr(session, "metadata", None))

        clinic_id_raw = metadata.get("clinic_id")
        plan_id_raw = metadata.get("plan_id")

        if clinic_id_raw and plan_id_raw:
            clinic_id = int(clinic_id_raw)
            plan_id = int(plan_id_raw)
            activate_or_extend_subscription_after_payment(db, clinic_id, plan_id)
            db.commit()

    return {"received": True, "type": event_type}


@router.post("/portal", response_model=BillingPortalOut)
def create_billing_portal(
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    if not STRIPE_SECRET_KEY:
        raise HTTPException(
            status_code=500,
            detail="Stripe is not configured. Missing STRIPE_SECRET_KEY.",
        )

    clinic_id = _resolve_clinic_id_for_user(db, current_user)
    if not clinic_id:
        raise HTTPException(
            status_code=403,
            detail="Current account is not associated with a clinic.",
        )

    clinic = db.query(models.Clinic).filter(models.Clinic.id == clinic_id).first()
    if not clinic:
        raise HTTPException(status_code=404, detail="Clinic not found.")

    customer_id = get_or_create_stripe_customer_for_clinic(db, clinic)

    portal = stripe.billing_portal.Session.create(
        customer=customer_id,
        return_url=get_frontend_success_url(),
    )

    db.commit()
    return BillingPortalOut(url=portal["url"])