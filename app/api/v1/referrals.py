# Path: backend/app/api/v1/referrals.py

from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app import models
from app.core.security import get_current_provider_for_user, get_current_user
from app.db import get_db
from app.schemas.referral import ReferralCreate, ReferralOut, ReferralReject

router = APIRouter(prefix="/referrals", tags=["referrals"])

CLINIC_WIDE_ROLES = {
    "clinic_admin",
    "assistant",
    "reception",
    "receptionist",
}
STAFF_VIEW_ROLES = {
    "clinic_admin",
    "assistant",
    "reception",
    "receptionist",
    "doctor",
}


def _normalize_clinic_role(value: Optional[str]) -> Optional[str]:
    if value == "receptionist":
        return "reception"
    return value


def _get_my_provider_profile(db: Session, current_user):
    provider = get_current_provider_for_user(db, current_user)
    if not provider:
        raise HTTPException(status_code=404, detail="Provider profile not linked to this user")
    if hasattr(provider, "status") and provider.status != "approved" and current_user.role != "admin":
        raise HTTPException(status_code=403, detail="Provider profile not approved")
    return provider


def _get_episode_or_404(db: Session, episode_id: int) -> models.CareEpisode:
    ep = db.query(models.CareEpisode).filter(models.CareEpisode.id == episode_id).first()
    if not ep:
        raise HTTPException(status_code=404, detail="Care episode not found")
    return ep


def _get_referral_or_404(db: Session, referral_id: int) -> models.Referral:
    r = db.query(models.Referral).filter(models.Referral.id == referral_id).first()
    if not r:
        raise HTTPException(status_code=404, detail="Referral not found")
    return r


def _get_active_staff_memberships(db: Session, current_user) -> List[models.ClinicMembership]:
    return (
        db.query(models.ClinicMembership)
        .filter(
            models.ClinicMembership.user_id == current_user.id,
            models.ClinicMembership.is_active == True,  # noqa: E712
        )
        .all()
    )


def _get_staff_scope(db: Session, current_user) -> dict:
    memberships = _get_active_staff_memberships(db, current_user)

    clinic_ids: List[int] = []
    doctor_ids: List[int] = []
    has_clinic_wide_access = False

    for membership in memberships:
        role = _normalize_clinic_role(getattr(membership, "role", None))
        clinic_id = getattr(membership, "clinic_id", None)
        provider_doctor_id = getattr(membership, "provider_doctor_id", None)

        if role not in STAFF_VIEW_ROLES:
            continue

        if clinic_id is not None and clinic_id not in clinic_ids:
            clinic_ids.append(clinic_id)

        if role in CLINIC_WIDE_ROLES:
            has_clinic_wide_access = True

        if role == "doctor" and provider_doctor_id is not None and provider_doctor_id not in doctor_ids:
            doctor_ids.append(provider_doctor_id)

    return {
        "clinic_ids": clinic_ids,
        "doctor_ids": doctor_ids,
        "has_clinic_wide_access": has_clinic_wide_access,
    }


def _ensure_owner_or_admin(db: Session, episode: models.CareEpisode, current_user):
    if current_user.role == "admin":
        return
    if current_user.role != "provider":
        raise HTTPException(status_code=403, detail="Not enough permissions")
    my_provider = _get_my_provider_profile(db, current_user)
    if episode.owner_provider_id != my_provider.id:
        raise HTTPException(status_code=403, detail="Not allowed")


def _staff_referral_base_query(db: Session, current_user):
    scope = _get_staff_scope(db, current_user)
    clinic_ids = scope["clinic_ids"]
    doctor_ids = scope["doctor_ids"]
    has_clinic_wide_access = scope["has_clinic_wide_access"]

    if not clinic_ids:
        raise HTTPException(status_code=403, detail="Not enough permissions")

    clinic_provider_ids = (
        select(models.Provider.id)
        .where(models.Provider.clinic_id.in_(clinic_ids))
    )

    query = (
        db.query(models.Referral)
        .filter(
            or_(
                models.Referral.to_provider_id.in_(clinic_provider_ids),
                models.Referral.from_provider_id.in_(clinic_provider_ids),
            )
        )
    )

    if has_clinic_wide_access:
        return query

    if doctor_ids:
        episode_ids_for_doctor = (
            select(models.Appointment.episode_id)
            .where(
                models.Appointment.doctor_id.in_(doctor_ids),
                models.Appointment.episode_id.isnot(None),
            )
        )
        return query.filter(models.Referral.episode_id.in_(episode_ids_for_doctor))

    return query.filter(False)


def _staff_can_access_referral(db: Session, referral: models.Referral, current_user) -> bool:
    scope = _get_staff_scope(db, current_user)
    clinic_ids = scope["clinic_ids"]
    doctor_ids = scope["doctor_ids"]
    has_clinic_wide_access = scope["has_clinic_wide_access"]

    if not clinic_ids:
        return False

    provider_ids = []
    if referral.from_provider_id is not None:
        provider_ids.append(referral.from_provider_id)
    if referral.to_provider_id is not None:
        provider_ids.append(referral.to_provider_id)

    if provider_ids:
        providers = (
            db.query(models.Provider)
            .filter(models.Provider.id.in_(provider_ids))
            .all()
        )
        provider_clinic_ids = [getattr(p, "clinic_id", None) for p in providers]
        if not any(clinic_id in clinic_ids for clinic_id in provider_clinic_ids):
            return False

    if has_clinic_wide_access:
        return True

    if doctor_ids:
        doctor_episode_exists = (
            db.query(models.Appointment)
            .filter(
                models.Appointment.episode_id == referral.episode_id,
                models.Appointment.doctor_id.in_(doctor_ids),
            )
            .first()
        )
        return doctor_episode_exists is not None

    return False


@router.get("/inbox", response_model=List[ReferralOut])
def inbox(
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    if current_user.role == "admin":
        return db.query(models.Referral).order_by(models.Referral.id.desc()).all()

    if current_user.role == "provider":
        my_provider = _get_my_provider_profile(db, current_user)
        return (
            db.query(models.Referral)
            .filter(models.Referral.to_provider_id == my_provider.id)
            .order_by(models.Referral.id.desc())
            .all()
        )

    return _staff_referral_base_query(db, current_user).order_by(models.Referral.id.desc()).all()


@router.post("/care-episodes/{episode_id}", response_model=ReferralOut, status_code=status.HTTP_201_CREATED)
def create_referral_for_episode(
    episode_id: int,
    payload: ReferralCreate,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    episode = _get_episode_or_404(db, episode_id)
    _ensure_owner_or_admin(db, episode, current_user)

    to_provider = db.query(models.Provider).filter(models.Provider.id == payload.to_provider_id).first()
    if not to_provider:
        raise HTTPException(status_code=400, detail="Target provider does not exist")

    if payload.to_provider_id == episode.owner_provider_id:
        raise HTTPException(status_code=400, detail="Cannot refer to the same provider")

    referral = models.Referral(
        episode_id=episode.id,
        from_provider_id=episode.owner_provider_id,
        to_provider_id=payload.to_provider_id,
        reason=payload.reason,
        status="pending",
        rejection_reason=None,
    )
    db.add(referral)
    db.commit()
    db.refresh(referral)
    return referral


@router.get("/care-episodes/{episode_id}", response_model=List[ReferralOut])
def list_referrals_for_episode(
    episode_id: int,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    episode = _get_episode_or_404(db, episode_id)

    if current_user.role == "admin":
        pass
    elif current_user.role == "provider":
        my_provider = _get_my_provider_profile(db, current_user)
        if episode.owner_provider_id != my_provider.id:
            incoming_or_outgoing = (
                db.query(models.Referral)
                .filter(
                    models.Referral.episode_id == episode.id,
                    or_(
                        models.Referral.to_provider_id == my_provider.id,
                        models.Referral.from_provider_id == my_provider.id,
                    ),
                )
                .first()
            )
            if not incoming_or_outgoing:
                raise HTTPException(status_code=403, detail="Not allowed")
    else:
        base_query = _staff_referral_base_query(db, current_user).filter(
            models.Referral.episode_id == episode.id
        )
        sample = base_query.first()
        if not sample:
            raise HTTPException(status_code=403, detail="Not allowed")

    return (
        db.query(models.Referral)
        .filter(models.Referral.episode_id == episode.id)
        .order_by(models.Referral.id.asc())
        .all()
    )


@router.post("/{referral_id}/accept", response_model=ReferralOut)
def accept_referral(
    referral_id: int,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    referral = _get_referral_or_404(db, referral_id)

    if current_user.role == "admin":
        pass
    elif current_user.role == "provider":
        my_provider = _get_my_provider_profile(db, current_user)
        if referral.to_provider_id != my_provider.id:
            raise HTTPException(status_code=403, detail="Not allowed")
    else:
        if not _staff_can_access_referral(db, referral, current_user):
            raise HTTPException(status_code=403, detail="Not allowed")

    if referral.status != "pending":
        raise HTTPException(status_code=409, detail="Referral is not pending")

    referral.status = "accepted"
    referral.rejection_reason = None

    db.commit()
    db.refresh(referral)
    return referral


@router.post("/{referral_id}/reject", response_model=ReferralOut)
def reject_referral(
    referral_id: int,
    payload: ReferralReject,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    referral = _get_referral_or_404(db, referral_id)

    if current_user.role == "admin":
        pass
    elif current_user.role == "provider":
        my_provider = _get_my_provider_profile(db, current_user)
        if referral.to_provider_id != my_provider.id:
            raise HTTPException(status_code=403, detail="Not allowed")
    else:
        if not _staff_can_access_referral(db, referral, current_user):
            raise HTTPException(status_code=403, detail="Not allowed")

    if referral.status != "pending":
        raise HTTPException(status_code=409, detail="Referral is not pending")

    referral.status = "rejected"
    referral.rejection_reason = payload.rejection_reason

    db.commit()
    db.refresh(referral)
    return referral


@router.post("/{referral_id}/complete", response_model=ReferralOut)
def complete_referral(
    referral_id: int,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    referral = _get_referral_or_404(db, referral_id)

    if current_user.role == "admin":
        pass
    elif current_user.role == "provider":
        my_provider = _get_my_provider_profile(db, current_user)
        if referral.to_provider_id != my_provider.id:
            raise HTTPException(status_code=403, detail="Not allowed")
    else:
        if not _staff_can_access_referral(db, referral, current_user):
            raise HTTPException(status_code=403, detail="Not allowed")

    if referral.status != "accepted":
        raise HTTPException(status_code=409, detail="Referral must be accepted before completing")

    referral.status = "completed"

    db.commit()
    db.refresh(referral)
    return referral