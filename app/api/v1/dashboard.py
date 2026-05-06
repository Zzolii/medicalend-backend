# Path: backend/app/api/v1/dashboard.py

from datetime import datetime, time

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.core.security import get_current_provider_for_user, get_current_user
from app.core.timezone import RO_TZ
from app.db import get_db
from app.models.appointment import Appointment as AppointmentModel
from app.models.clinic_membership import ClinicMembership as ClinicMembershipModel
from app.models.provider import Provider as ProviderModel
from app.models.referral import Referral as ReferralModel
from app.schemas.dashboard import ProviderDashboardOut

router = APIRouter(prefix="/dashboard", tags=["dashboard"])

REFERRAL_ACCESS_STATUSES = ("accepted", "in_progress", "completed")
CLINIC_WIDE_VIEW_ROLES = {
    "clinic_admin",
    "assistant",
    "reception",
    "receptionist",
}


def _normalize_clinic_role(value: str | None) -> str | None:
    if value == "receptionist":
        return "reception"
    return value


def _get_my_provider_profile(db: Session, current_user) -> ProviderModel:
    provider = get_current_provider_for_user(db, current_user)
    if getattr(provider, "status", None) != "approved" and current_user.role != "admin":
        raise HTTPException(status_code=403, detail="Provider profile not approved")
    return provider


def _provider_visible_appointments_query(db: Session, provider_id: int):
    referred_episode_ids = (
        select(ReferralModel.episode_id)
        .where(
            ReferralModel.to_provider_id == provider_id,
            ReferralModel.status.in_(REFERRAL_ACCESS_STATUSES),
        )
    )

    return (
        db.query(AppointmentModel)
        .filter(
            or_(
                AppointmentModel.provider_id == provider_id,
                AppointmentModel.episode_id.in_(referred_episode_ids),
            )
        )
    )


def _get_staff_scope(db: Session, current_user) -> dict:
    memberships = (
        db.query(ClinicMembershipModel)
        .filter(
            ClinicMembershipModel.user_id == current_user.id,
            ClinicMembershipModel.is_active == True,  # noqa: E712
        )
        .all()
    )

    clinic_ids: list[int] = []
    doctor_ids: list[int] = []
    has_clinic_wide_access = False

    for membership in memberships:
        role = _normalize_clinic_role(getattr(membership, "role", None))
        clinic_id = getattr(membership, "clinic_id", None)
        provider_doctor_id = getattr(membership, "provider_doctor_id", None)

        if clinic_id is not None and clinic_id not in clinic_ids:
            clinic_ids.append(clinic_id)

        if role in CLINIC_WIDE_VIEW_ROLES:
            has_clinic_wide_access = True

        if role == "doctor" and provider_doctor_id is not None and provider_doctor_id not in doctor_ids:
            doctor_ids.append(provider_doctor_id)

    return {
        "clinic_ids": clinic_ids,
        "doctor_ids": doctor_ids,
        "has_clinic_wide_access": has_clinic_wide_access,
    }


def _clinic_visible_appointments_query(
    db: Session,
    clinic_ids: list[int],
    doctor_ids: list[int] | None = None,
    clinic_wide: bool = True,
):
    provider_ids = (
        select(ProviderModel.id)
        .where(ProviderModel.clinic_id.in_(clinic_ids))
    )

    query = (
        db.query(AppointmentModel)
        .filter(
            or_(
                AppointmentModel.clinic_id.in_(clinic_ids),
                AppointmentModel.provider_id.in_(provider_ids),
            )
        )
    )

    if not clinic_wide:
        if not doctor_ids:
            return query.filter(False)
        query = query.filter(AppointmentModel.doctor_id.in_(doctor_ids))

    return query


@router.get("/provider", response_model=ProviderDashboardOut)
def provider_dashboard(
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    provider = _get_my_provider_profile(db, current_user)

    pending_referrals = (
        db.query(ReferralModel)
        .filter(
            ReferralModel.to_provider_id == provider.id,
            ReferralModel.status == "pending",
        )
        .order_by(ReferralModel.id.desc())
        .all()
    )

    now = datetime.now(RO_TZ)
    start_of_day = datetime.combine(now.date(), time.min).replace(tzinfo=RO_TZ)
    end_of_day = datetime.combine(now.date(), time.max).replace(tzinfo=RO_TZ)

    scope = _get_staff_scope(db, current_user)
    clinic_ids = scope["clinic_ids"]

    if clinic_ids:
        today_appointments = (
            _clinic_visible_appointments_query(
                db,
                clinic_ids,
                doctor_ids=scope["doctor_ids"],
                clinic_wide=scope["has_clinic_wide_access"],
            )
            .filter(AppointmentModel.start_time >= start_of_day)
            .filter(AppointmentModel.start_time <= end_of_day)
            .order_by(AppointmentModel.start_time.asc())
            .all()
        )
    else:
        today_appointments = (
            _provider_visible_appointments_query(db, provider.id)
            .filter(AppointmentModel.start_time >= start_of_day)
            .filter(AppointmentModel.start_time <= end_of_day)
            .order_by(AppointmentModel.start_time.asc())
            .all()
        )

    return {
        "provider_id": provider.id,
        "pending_referrals": pending_referrals,
        "today_appointments": today_appointments,
    }