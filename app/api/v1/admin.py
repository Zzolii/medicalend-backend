# Path: backend/app/api/v1/admin.py

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import List

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app import models
from app.core.security import require_roles
from app.db import get_db
from app.schemas.admin import (
    AdminProviderRow,
    RejectProviderRequest,
    AdminReferralRow,
    AdminStatsOut,
)
from app.schemas.subscription import (
    ClinicSubscriptionAdminRow,
    ClinicSubscriptionCreate,
    ClinicSubscriptionOut,
    ClinicSubscriptionUpdate,
    SubscriptionPlanCreate,
    SubscriptionPlanOut,
    SubscriptionPlanUpdate,
)
from app.services.subscriptions import (
    ensure_clinic_trial_subscription,
    ensure_default_trial_plan,
)

router = APIRouter(prefix="/admin", tags=["admin"])


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _serialize_provider_row(provider: models.Provider) -> AdminProviderRow:
    return AdminProviderRow(
        id=provider.id,
        user_id=getattr(provider, "user_id", None),
        clinic_id=getattr(provider, "clinic_id", None),
        status=getattr(provider, "status", None),
        rejection_reason=getattr(provider, "rejection_reason", None),
        provider_type=getattr(provider, "provider_type", None),
        name=getattr(provider, "name", None),
        specialty=getattr(provider, "specialty", None),
        services_offered=getattr(provider, "services_offered", None),
        license_number=getattr(provider, "license_number", None),
        cui=getattr(provider, "cui", None),
        trade_register_number=getattr(provider, "trade_register_number", None),
        contact_person_name=getattr(provider, "contact_person_name", None),
        contact_email=getattr(provider, "contact_email", None),
        contact_phone=getattr(provider, "contact_phone", None),
        phone=getattr(provider, "phone", None),
        email=getattr(provider, "email", None),
        address_line=getattr(provider, "address_line", None),
        city=getattr(provider, "city", None),
        county=getattr(provider, "county", None),
        postal_code=getattr(provider, "postal_code", None),
        country=getattr(provider, "country", None),
        coverage_area=getattr(provider, "coverage_area", None),
        sanitary_authorization_number=getattr(
            provider, "sanitary_authorization_number", None
        ),
        sanitary_authorization_expires_at=getattr(
            provider, "sanitary_authorization_expires_at", None
        ),
        healthcare_compliance_confirmed=getattr(
            provider, "healthcare_compliance_confirmed", None
        ),
        provider_agreement_accepted=getattr(
            provider, "provider_agreement_accepted", None
        ),
        is_active=getattr(provider, "is_active", None),
        fhir_id=getattr(provider, "fhir_id", None),
        created_at=getattr(provider, "created_at", None),
    )


def _serialize_subscription_row(
    db: Session,
    sub: models.ClinicSubscription,
) -> ClinicSubscriptionAdminRow:
    clinic_name = None
    plan_code = None
    plan_name = None
    price_eur = None
    duration_days = None

    clinic = db.query(models.Clinic).filter(models.Clinic.id == sub.clinic_id).first()
    if clinic:
        clinic_name = getattr(clinic, "name", None)

    plan = (
        db.query(models.SubscriptionPlan)
        .filter(models.SubscriptionPlan.id == sub.plan_id)
        .first()
    )
    if plan:
        plan_code = getattr(plan, "code", None)
        plan_name = getattr(plan, "name", None)
        price_eur = getattr(plan, "price_eur", None)
        duration_days = getattr(plan, "duration_days", None)

    return ClinicSubscriptionAdminRow(
        id=sub.id,
        clinic_id=sub.clinic_id,
        clinic_name=clinic_name,
        plan_id=sub.plan_id,
        plan_code=plan_code,
        plan_name=plan_name,
        price_eur=price_eur,
        duration_days=duration_days,
        status=sub.status,
        starts_at=sub.starts_at,
        ends_at=sub.ends_at,
        created_at=getattr(sub, "created_at", None),
    )


def _serialize_plan(plan: models.SubscriptionPlan) -> SubscriptionPlanOut:
    return SubscriptionPlanOut(
        id=plan.id,
        code=getattr(plan, "code", None),
        name=getattr(plan, "name", None),
        description=None,
        price_eur=getattr(plan, "price_eur", None),
        duration_days=getattr(plan, "duration_days", None),
        is_active=getattr(plan, "is_active", None),
        created_at=getattr(plan, "created_at", None),
    )


def _safe_count_model(db: Session, model) -> int:
    try:
        return db.query(model).count()
    except Exception:
        return 0


def _safe_count_attr_eq(db: Session, model, attr_name: str, value) -> int:
    try:
        attr = getattr(model, attr_name)
        return db.query(model).filter(attr == value).count()
    except Exception:
        return 0


def _safe_count_attr_in(db: Session, model, attr_name: str, values: list[str]) -> int:
    try:
        attr = getattr(model, attr_name)
        return db.query(model).filter(attr.in_(values)).count()
    except Exception:
        return 0


def _safe_count_created_since(
    db: Session,
    model,
    since: datetime,
    created_attr_name: str = "created_at",
) -> int:
    try:
        created_attr = getattr(model, created_attr_name)
        return db.query(model).filter(created_attr >= since).count()
    except Exception:
        return 0


def _safe_count_start_since(
    db: Session,
    model,
    since: datetime,
    start_attr_name: str = "start_time",
) -> int:
    try:
        start_attr = getattr(model, start_attr_name)
        return db.query(model).filter(start_attr >= since).count()
    except Exception:
        return 0


def _safe_subscription_expiring_soon(db: Session, now: datetime) -> int:
    try:
        end = now + timedelta(days=7)
        return (
            db.query(models.ClinicSubscription)
            .filter(models.ClinicSubscription.status.in_(["trialing", "active"]))
            .filter(models.ClinicSubscription.ends_at >= now)
            .filter(models.ClinicSubscription.ends_at <= end)
            .count()
        )
    except Exception:
        return 0


def _activate_approved_provider_user(db: Session, user_id: int | None) -> None:
    if not user_id:
        return

    user = db.query(models.User).filter(models.User.id == user_id).first()
    if not user:
        return

    if hasattr(user, "is_active"):
        user.is_active = True

    if hasattr(user, "is_email_verified"):
        user.is_email_verified = True

    if hasattr(user, "email_verified_at"):
        user.email_verified_at = utcnow()

    db.add(user)


def _activate_clinic_memberships_if_possible(
    db: Session,
    clinic_id: int | None,
) -> None:
    if not clinic_id:
        return

    memberships = (
        db.query(models.ClinicMembership)
        .filter(models.ClinicMembership.clinic_id == clinic_id)
        .all()
    )

    for membership in memberships:
        if hasattr(membership, "is_active"):
            membership.is_active = True
            db.add(membership)


def _deactivate_user_if_possible(db: Session, user_id: int | None) -> None:
    if not user_id:
        return

    user = db.query(models.User).filter(models.User.id == user_id).first()
    if not user:
        return

    if hasattr(user, "is_active"):
        user.is_active = False
        db.add(user)


def _deactivate_clinic_if_possible(db: Session, clinic_id: int | None) -> None:
    if not clinic_id:
        return

    clinic = db.query(models.Clinic).filter(models.Clinic.id == clinic_id).first()
    if not clinic:
        return

    if hasattr(clinic, "is_active"):
        clinic.is_active = False
        db.add(clinic)

    memberships = (
        db.query(models.ClinicMembership)
        .filter(models.ClinicMembership.clinic_id == clinic_id)
        .all()
    )
    for membership in memberships:
        if hasattr(membership, "is_active"):
            membership.is_active = False
            db.add(membership)

    subscriptions = (
        db.query(models.ClinicSubscription)
        .filter(models.ClinicSubscription.clinic_id == clinic_id)
        .all()
    )
    for subscription in subscriptions:
        if hasattr(subscription, "status"):
            subscription.status = "canceled"
            db.add(subscription)


@router.get("/stats", response_model=AdminStatsOut)
def admin_stats(
    db: Session = Depends(get_db),
    _admin=Depends(require_roles("admin")),
):
    now = utcnow()
    since_7d = now - timedelta(days=7)
    since_30d = now - timedelta(days=30)

    total_users = _safe_count_model(db, models.User)
    total_patients = _safe_count_model(db, models.Patient)
    total_providers = _safe_count_model(db, models.Provider)

    pending_providers = _safe_count_attr_eq(db, models.Provider, "status", "pending")
    approved_providers = _safe_count_attr_eq(db, models.Provider, "status", "approved")
    rejected_providers = _safe_count_attr_eq(db, models.Provider, "status", "rejected")

    total_clinics = _safe_count_model(db, models.Clinic)
    active_clinics = _safe_count_attr_eq(db, models.Clinic, "is_active", True)

    total_referrals = _safe_count_model(db, models.Referral)
    pending_referrals = _safe_count_attr_eq(db, models.Referral, "status", "pending")

    total_subscription_plans = _safe_count_model(db, models.SubscriptionPlan)
    active_subscription_plans = _safe_count_attr_eq(
        db,
        models.SubscriptionPlan,
        "is_active",
        True,
    )

    total_clinic_subscriptions = _safe_count_model(db, models.ClinicSubscription)
    active_subscriptions = _safe_count_attr_eq(
        db,
        models.ClinicSubscription,
        "status",
        "active",
    )
    trialing_subscriptions = _safe_count_attr_eq(
        db,
        models.ClinicSubscription,
        "status",
        "trialing",
    )
    expired_subscriptions = _safe_count_attr_eq(
        db,
        models.ClinicSubscription,
        "status",
        "expired",
    )
    canceled_subscriptions = _safe_count_attr_eq(
        db,
        models.ClinicSubscription,
        "status",
        "canceled",
    )

    subscriptions_expiring_soon = _safe_subscription_expiring_soon(db, now)

    active_users_30d = _safe_count_created_since(db, models.User, since_30d)
    new_patients_30d = _safe_count_created_since(db, models.Patient, since_30d)

    appointments_7d = _safe_count_start_since(
        db,
        models.Appointment,
        since_7d.replace(tzinfo=None),
    )
    appointments_total = _safe_count_model(db, models.Appointment)

    care_notes_total = _safe_count_model(db, models.CareNote)
    care_tasks_total = _safe_count_model(db, models.CareTask)
    referrals_total_for_timeline = total_referrals
    appointments_total_for_timeline = appointments_total
    documents_total = _safe_count_model(db, models.MedicalDocument)

    timeline_entries = (
        care_notes_total
        + care_tasks_total
        + referrals_total_for_timeline
        + appointments_total_for_timeline
        + documents_total
    )

    return AdminStatsOut(
        total_users=total_users,
        total_patients=total_patients,
        total_providers=total_providers,
        pending_providers=pending_providers,
        approved_providers=approved_providers,
        rejected_providers=rejected_providers,
        total_clinics=total_clinics,
        active_clinics=active_clinics,
        total_referrals=total_referrals,
        pending_referrals=pending_referrals,
        total_subscription_plans=total_subscription_plans,
        active_subscription_plans=active_subscription_plans,
        total_clinic_subscriptions=total_clinic_subscriptions,
        active_subscriptions=active_subscriptions,
        trialing_subscriptions=trialing_subscriptions,
        expired_subscriptions=expired_subscriptions,
        canceled_subscriptions=canceled_subscriptions,
        subscriptions_expiring_soon=subscriptions_expiring_soon,
        active_users_30d=active_users_30d,
        new_patients_30d=new_patients_30d,
        appointments_7d=appointments_7d,
        appointments_total=appointments_total,
        timeline_entries=timeline_entries,
        documents_total=documents_total,
    )


@router.get("/providers", response_model=List[AdminProviderRow])
def list_admin_providers(
    db: Session = Depends(get_db),
    _admin=Depends(require_roles("admin")),
):
    rows = (
        db.query(models.Provider)
        .order_by(models.Provider.created_at.desc(), models.Provider.id.desc())
        .all()
    )
    return [_serialize_provider_row(item) for item in rows]


@router.get("/providers/pending", response_model=List[AdminProviderRow])
def list_pending_admin_providers(
    db: Session = Depends(get_db),
    _admin=Depends(require_roles("admin")),
):
    rows = (
        db.query(models.Provider)
        .filter(models.Provider.status == "pending")
        .order_by(models.Provider.created_at.desc(), models.Provider.id.desc())
        .all()
    )
    return [_serialize_provider_row(item) for item in rows]


@router.post("/providers/{provider_id}/approve", response_model=AdminProviderRow)
def approve_provider(
    provider_id: int,
    db: Session = Depends(get_db),
    _admin=Depends(require_roles("admin")),
):
    provider = db.query(models.Provider).filter(models.Provider.id == provider_id).first()
    if not provider:
        raise HTTPException(status_code=404, detail="Provider not found.")

    provider.status = "approved"

    if hasattr(provider, "rejection_reason"):
        provider.rejection_reason = None

    if hasattr(provider, "is_active"):
        provider.is_active = True

    clinic_id = getattr(provider, "clinic_id", None)
    user_id = getattr(provider, "user_id", None)

    if clinic_id:
        ensure_default_trial_plan(db)
        ensure_clinic_trial_subscription(db, clinic_id)

        clinic = db.query(models.Clinic).filter(models.Clinic.id == clinic_id).first()
        if clinic and hasattr(clinic, "is_active"):
            clinic.is_active = True
            db.add(clinic)

        _activate_clinic_memberships_if_possible(db, clinic_id)

    _activate_approved_provider_user(db, user_id)

    db.add(provider)
    db.commit()
    db.refresh(provider)

    return _serialize_provider_row(provider)


@router.post("/providers/{provider_id}/reject", response_model=AdminProviderRow)
def reject_provider(
    provider_id: int,
    payload: RejectProviderRequest,
    db: Session = Depends(get_db),
    _admin=Depends(require_roles("admin")),
):
    provider = db.query(models.Provider).filter(models.Provider.id == provider_id).first()
    if not provider:
        raise HTTPException(status_code=404, detail="Provider not found.")

    provider.status = "rejected"

    if hasattr(provider, "rejection_reason"):
        provider.rejection_reason = payload.reason

    if hasattr(provider, "is_active"):
        provider.is_active = False

    db.add(provider)
    db.commit()
    db.refresh(provider)

    return _serialize_provider_row(provider)


@router.delete("/providers/{provider_id}", response_model=AdminProviderRow)
def delete_provider(
    provider_id: int,
    db: Session = Depends(get_db),
    _admin=Depends(require_roles("admin")),
):
    provider = db.query(models.Provider).filter(models.Provider.id == provider_id).first()
    if not provider:
        raise HTTPException(status_code=404, detail="Provider not found.")

    if hasattr(provider, "is_active"):
        provider.is_active = False

    if hasattr(provider, "status"):
        provider.status = "rejected"

    if hasattr(provider, "rejection_reason"):
        provider.rejection_reason = "Deleted/deactivated by platform admin."

    clinic_id = getattr(provider, "clinic_id", None)
    user_id = getattr(provider, "user_id", None)

    _deactivate_user_if_possible(db, user_id)
    _deactivate_clinic_if_possible(db, clinic_id)

    db.add(provider)
    db.commit()
    db.refresh(provider)

    return _serialize_provider_row(provider)


@router.get("/referrals", response_model=List[AdminReferralRow])
def list_admin_referrals(
    db: Session = Depends(get_db),
    _admin=Depends(require_roles("admin")),
):
    referrals = db.query(models.Referral).order_by(models.Referral.id.desc()).all()

    return [
        AdminReferralRow(
            id=item.id,
            episode_id=item.episode_id,
            from_provider_id=item.from_provider_id,
            to_provider_id=item.to_provider_id,
            status=item.status,
            reason=getattr(item, "reason", None),
            rejection_reason=getattr(item, "rejection_reason", None),
            created_at=getattr(item, "created_at", None),
        )
        for item in referrals
    ]


@router.get("/referrals/recent", response_model=List[AdminReferralRow])
def list_recent_admin_referrals(
    limit: int = 20,
    db: Session = Depends(get_db),
    _admin=Depends(require_roles("admin")),
):
    referrals = (
        db.query(models.Referral)
        .order_by(models.Referral.id.desc())
        .limit(limit)
        .all()
    )

    return [
        AdminReferralRow(
            id=item.id,
            episode_id=item.episode_id,
            from_provider_id=item.from_provider_id,
            to_provider_id=item.to_provider_id,
            status=item.status,
            reason=getattr(item, "reason", None),
            rejection_reason=getattr(item, "rejection_reason", None),
            created_at=getattr(item, "created_at", None),
        )
        for item in referrals
    ]


@router.get("/subscription-plans", response_model=List[SubscriptionPlanOut])
def list_subscription_plans(
    db: Session = Depends(get_db),
    _admin=Depends(require_roles("admin")),
):
    ensure_default_trial_plan(db)
    db.commit()

    rows = (
        db.query(models.SubscriptionPlan)
        .order_by(models.SubscriptionPlan.id.desc())
        .all()
    )
    return [_serialize_plan(item) for item in rows]


@router.post(
    "/subscription-plans",
    response_model=SubscriptionPlanOut,
    status_code=status.HTTP_201_CREATED,
)
def create_subscription_plan(
    payload: SubscriptionPlanCreate,
    db: Session = Depends(get_db),
    _admin=Depends(require_roles("admin")),
):
    existing = (
        db.query(models.SubscriptionPlan)
        .filter(models.SubscriptionPlan.code == payload.code)
        .first()
    )
    if existing:
        raise HTTPException(
            status_code=400,
            detail="A subscription plan with this code already exists.",
        )

    plan = models.SubscriptionPlan(
        code=payload.code,
        name=payload.name,
        price_eur=payload.price_eur,
        duration_days=payload.duration_days,
        is_active=payload.is_active,
    )
    db.add(plan)
    db.commit()
    db.refresh(plan)
    return _serialize_plan(plan)


@router.patch("/subscription-plans/{plan_id}", response_model=SubscriptionPlanOut)
def update_subscription_plan(
    plan_id: int,
    payload: SubscriptionPlanUpdate,
    db: Session = Depends(get_db),
    _admin=Depends(require_roles("admin")),
):
    plan = (
        db.query(models.SubscriptionPlan)
        .filter(models.SubscriptionPlan.id == plan_id)
        .first()
    )
    if not plan:
        raise HTTPException(status_code=404, detail="Subscription plan not found.")

    data = payload.model_dump(exclude_unset=True)
    data.pop("description", None)

    for key, value in data.items():
        setattr(plan, key, value)

    db.add(plan)
    db.commit()
    db.refresh(plan)
    return _serialize_plan(plan)


@router.get(
    "/clinic-subscriptions",
    response_model=List[ClinicSubscriptionAdminRow],
)
def list_clinic_subscriptions(
    db: Session = Depends(get_db),
    _admin=Depends(require_roles("admin")),
):
    rows = (
        db.query(models.ClinicSubscription)
        .order_by(models.ClinicSubscription.id.desc())
        .all()
    )
    return [_serialize_subscription_row(db, item) for item in rows]


@router.post(
    "/clinic-subscriptions",
    response_model=ClinicSubscriptionOut,
    status_code=status.HTTP_201_CREATED,
)
def create_clinic_subscription(
    payload: ClinicSubscriptionCreate,
    db: Session = Depends(get_db),
    _admin=Depends(require_roles("admin")),
):
    clinic = db.query(models.Clinic).filter(models.Clinic.id == payload.clinic_id).first()
    if not clinic:
        raise HTTPException(status_code=404, detail="Clinic not found.")

    plan = (
        db.query(models.SubscriptionPlan)
        .filter(models.SubscriptionPlan.id == payload.plan_id)
        .first()
    )
    if not plan:
        raise HTTPException(status_code=404, detail="Subscription plan not found.")

    if payload.starts_at >= payload.ends_at:
        raise HTTPException(
            status_code=400,
            detail="starts_at must be before ends_at.",
        )

    sub = models.ClinicSubscription(
        clinic_id=payload.clinic_id,
        plan_id=payload.plan_id,
        status=payload.status,
        starts_at=payload.starts_at,
        ends_at=payload.ends_at,
    )
    db.add(sub)
    db.commit()
    db.refresh(sub)

    return ClinicSubscriptionOut(
        id=sub.id,
        clinic_id=sub.clinic_id,
        plan_id=sub.plan_id,
        status=sub.status,
        starts_at=sub.starts_at,
        ends_at=sub.ends_at,
        created_at=getattr(sub, "created_at", None),
    )


@router.patch(
    "/clinic-subscriptions/{subscription_id}",
    response_model=ClinicSubscriptionOut,
)
def update_clinic_subscription(
    subscription_id: int,
    payload: ClinicSubscriptionUpdate,
    db: Session = Depends(get_db),
    _admin=Depends(require_roles("admin")),
):
    sub = (
        db.query(models.ClinicSubscription)
        .filter(models.ClinicSubscription.id == subscription_id)
        .first()
    )
    if not sub:
        raise HTTPException(status_code=404, detail="Clinic subscription not found.")

    data = payload.model_dump(exclude_unset=True)

    if "plan_id" in data:
        plan = (
            db.query(models.SubscriptionPlan)
            .filter(models.SubscriptionPlan.id == data["plan_id"])
            .first()
        )
        if not plan:
            raise HTTPException(
                status_code=404,
                detail="Subscription plan not found.",
            )

    next_starts_at = data.get("starts_at", sub.starts_at)
    next_ends_at = data.get("ends_at", sub.ends_at)

    if next_starts_at >= next_ends_at:
        raise HTTPException(
            status_code=400,
            detail="starts_at must be before ends_at.",
        )

    for key, value in data.items():
        setattr(sub, key, value)

    db.add(sub)
    db.commit()
    db.refresh(sub)

    return ClinicSubscriptionOut(
        id=sub.id,
        clinic_id=sub.clinic_id,
        plan_id=sub.plan_id,
        status=sub.status,
        starts_at=sub.starts_at,
        ends_at=sub.ends_at,
        created_at=getattr(sub, "created_at", None),
    )