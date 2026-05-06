# Path: backend/app/api/v1/google_calendar.py

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from app import models
from app.core.config import settings
from app.core.security import get_current_user
from app.core.subscription_guard import resolve_clinic_id_for_user
from app.db import get_db
from app.integrations.google_calendar.client import (
    build_calendar_service,
    integration_has_usable_tokens,
    query_freebusy,
)
from app.integrations.google_calendar.oauth import (
    GOOGLE_TOKEN_URL,
    build_google_oauth_authorization_url,
    create_google_oauth_state,
    decode_google_oauth_state,
    ensure_google_oauth_configured,
)
from app.schemas.google_calendar import (
    GoogleCalendarFreeBusyTestIn,
    GoogleCalendarFreeBusyTestOut,
    GoogleCalendarIntegrationCreate,
    GoogleCalendarIntegrationOut,
    GoogleCalendarIntegrationUpdate,
)

router = APIRouter(prefix="/integrations/google-calendar", tags=["google-calendar"])

ALLOWED_MANAGE_ROLES = {"clinic_admin"}
ALLOWED_VIEW_ROLES = {"clinic_admin", "doctor", "assistant", "reception", "receptionist"}


def _normalize_clinic_role(value: str | None) -> str | None:
    if value == "receptionist":
        return "reception"
    return value


def _get_active_membership_for_clinic(db: Session, current_user, clinic_id: int):
    return (
        db.query(models.ClinicMembership)
        .filter(
            models.ClinicMembership.user_id == current_user.id,
            models.ClinicMembership.clinic_id == clinic_id,
            models.ClinicMembership.is_active == True,  # noqa: E712
        )
        .first()
    )


def _ensure_google_calendar_view_access(db: Session, current_user, clinic_id: int) -> None:
    if current_user.role == "admin":
        return

    membership = _get_active_membership_for_clinic(db, current_user, clinic_id)
    if not membership:
        raise HTTPException(status_code=403, detail="Clinic membership required.")

    role = _normalize_clinic_role(getattr(membership, "role", None))
    if role not in ALLOWED_VIEW_ROLES:
        raise HTTPException(status_code=403, detail="Not enough clinic permissions.")


def _ensure_google_calendar_manage_access(db: Session, current_user, clinic_id: int) -> None:
    if current_user.role == "admin":
        return

    membership = _get_active_membership_for_clinic(db, current_user, clinic_id)
    if not membership:
        raise HTTPException(status_code=403, detail="Clinic membership required.")

    role = _normalize_clinic_role(getattr(membership, "role", None))
    if role not in ALLOWED_MANAGE_ROLES:
        raise HTTPException(status_code=403, detail="Only clinic admins can manage Google Calendar integration.")


def _resolve_current_clinic_id_or_403(db: Session, current_user) -> int:
    clinic_id = resolve_clinic_id_for_user(db, current_user)
    if not clinic_id:
        raise HTTPException(
            status_code=403,
            detail="Current account is not associated with a clinic.",
        )
    return clinic_id


def _ensure_provider_belongs_to_clinic(db: Session, provider_id: int, clinic_id: int) -> models.Provider:
    provider = (
        db.query(models.Provider)
        .filter(
            models.Provider.id == provider_id,
            models.Provider.clinic_id == clinic_id,
            models.Provider.is_active == True,  # noqa: E712
        )
        .first()
    )
    if not provider:
        raise HTTPException(
            status_code=400,
            detail="Provider does not belong to the current clinic.",
        )
    return provider


def _ensure_doctor_belongs_to_provider(
    db: Session,
    *,
    provider_id: int,
    doctor_id: int | None,
) -> None:
    if doctor_id is None:
        return

    doctor = (
        db.query(models.ProviderDoctor)
        .filter(
            models.ProviderDoctor.id == doctor_id,
            models.ProviderDoctor.provider_id == provider_id,
            models.ProviderDoctor.is_active == True,  # noqa: E712
        )
        .first()
    )
    if not doctor:
        raise HTTPException(
            status_code=400,
            detail="Doctor does not belong to the selected provider.",
        )


def _get_mapping_or_404(db: Session, mapping_id: int) -> models.GoogleCalendarIntegration:
    mapping = (
        db.query(models.GoogleCalendarIntegration)
        .filter(models.GoogleCalendarIntegration.id == mapping_id)
        .first()
    )
    if not mapping:
        raise HTTPException(status_code=404, detail="Google Calendar mapping not found.")
    return mapping


def _exchange_google_code_for_tokens(code: str) -> dict:
    ensure_google_oauth_configured()

    payload = urlencode(
        {
            "code": code,
            "client_id": settings.GOOGLE_CLIENT_ID,
            "client_secret": settings.GOOGLE_CLIENT_SECRET,
            "redirect_uri": settings.GOOGLE_OAUTH_REDIRECT_URI,
            "grant_type": "authorization_code",
        }
    ).encode("utf-8")

    request = Request(
        GOOGLE_TOKEN_URL,
        data=payload,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        method="POST",
    )

    try:
        with urlopen(request, timeout=20) as response:
            return json.loads(response.read().decode("utf-8"))
    except Exception as exc:
        raise HTTPException(status_code=400, detail="Google token exchange failed.") from exc


def _token_expires_at_from_response(token_response: dict) -> datetime | None:
    expires_in = token_response.get("expires_in")
    if not expires_in:
        return None

    try:
        seconds = int(expires_in)
    except (TypeError, ValueError):
        return None

    return datetime.now(timezone.utc) + timedelta(seconds=seconds)


def _get_primary_calendar_email(mapping: models.GoogleCalendarIntegration) -> str | None:
    try:
        service = build_calendar_service(mapping)
        primary = service.calendars().get(calendarId="primary").execute()
        return primary.get("id")
    except Exception:
        return None


@router.get("/oauth/start")
def start_google_calendar_oauth(
    provider_id: int = Query(...),
    doctor_id: int | None = Query(None),
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    clinic_id = _resolve_current_clinic_id_or_403(db, current_user)
    _ensure_google_calendar_manage_access(db, current_user, clinic_id)

    _ensure_provider_belongs_to_clinic(db, provider_id, clinic_id)
    _ensure_doctor_belongs_to_provider(
        db,
        provider_id=provider_id,
        doctor_id=doctor_id,
    )

    state = create_google_oauth_state(
        user_id=current_user.id,
        clinic_id=clinic_id,
        provider_id=provider_id,
        doctor_id=doctor_id,
    )

    authorization_url = build_google_oauth_authorization_url(state=state)

    return {
        "authorization_url": authorization_url,
    }


@router.get("/oauth/callback")
def google_calendar_oauth_callback(
    code: str | None = Query(None),
    state: str | None = Query(None),
    error: str | None = Query(None),
    db: Session = Depends(get_db),
):
    if error:
        return RedirectResponse(
            url=f"{settings.FRONTEND_WEB_URL.rstrip('/')}?google_calendar=error&reason={error}"
        )

    if not code or not state:
        raise HTTPException(status_code=400, detail="Missing Google OAuth code or state.")

    decoded_state = decode_google_oauth_state(state)

    clinic_id = int(decoded_state["clinic_id"])
    provider_id = int(decoded_state["provider_id"])
    doctor_id = decoded_state.get("doctor_id")
    doctor_id = int(doctor_id) if doctor_id is not None else None

    provider = _ensure_provider_belongs_to_clinic(db, provider_id, clinic_id)
    _ensure_doctor_belongs_to_provider(
        db,
        provider_id=provider.id,
        doctor_id=doctor_id,
    )

    token_response = _exchange_google_code_for_tokens(code)

    access_token = token_response.get("access_token")
    refresh_token = token_response.get("refresh_token")
    scopes = token_response.get("scope")

    if not access_token:
        raise HTTPException(status_code=400, detail="Google did not return an access token.")

    existing = (
        db.query(models.GoogleCalendarIntegration)
        .filter(
            models.GoogleCalendarIntegration.clinic_id == clinic_id,
            models.GoogleCalendarIntegration.provider_id == provider_id,
            models.GoogleCalendarIntegration.doctor_id == doctor_id,
        )
        .order_by(models.GoogleCalendarIntegration.id.asc())
        .first()
    )

    mapping = existing or models.GoogleCalendarIntegration(
        clinic_id=clinic_id,
        provider_id=provider_id,
        doctor_id=doctor_id,
        google_calendar_id="primary",
        google_calendar_name="Primary calendar",
        sync_direction="google_bridge",
        status="connected",
        is_active=True,
    )

    mapping.access_token = access_token
    if refresh_token:
        mapping.refresh_token = refresh_token

    mapping.token_uri = GOOGLE_TOKEN_URL
    mapping.client_id = settings.GOOGLE_CLIENT_ID
    mapping.client_secret = settings.GOOGLE_CLIENT_SECRET
    mapping.scopes = scopes
    mapping.token_expires_at = _token_expires_at_from_response(token_response)
    mapping.status = "connected"
    mapping.is_active = True

    db.add(mapping)
    db.flush()

    google_account_email = _get_primary_calendar_email(mapping)
    if google_account_email:
        mapping.google_account_email = google_account_email

    db.add(mapping)
    db.commit()
    db.refresh(mapping)

    return RedirectResponse(
        url=f"{settings.FRONTEND_WEB_URL.rstrip('/')}?google_calendar=connected&mapping_id={mapping.id}"
    )


@router.get("/mappings", response_model=list[GoogleCalendarIntegrationOut])
def list_google_calendar_mappings(
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    clinic_id = _resolve_current_clinic_id_or_403(db, current_user)
    _ensure_google_calendar_view_access(db, current_user, clinic_id)

    return (
        db.query(models.GoogleCalendarIntegration)
        .filter(models.GoogleCalendarIntegration.clinic_id == clinic_id)
        .order_by(models.GoogleCalendarIntegration.id.desc())
        .all()
    )


@router.get("/mappings/{mapping_id}/calendars")
def list_available_google_calendars(
    mapping_id: int,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    mapping = _get_mapping_or_404(db, mapping_id)
    _ensure_google_calendar_manage_access(db, current_user, mapping.clinic_id)

    if not integration_has_usable_tokens(mapping):
        raise HTTPException(
            status_code=400,
            detail="Google Calendar OAuth tokens are not configured.",
        )

    try:
        service = build_calendar_service(mapping)
        response = service.calendarList().list().execute()
    except Exception as exc:
        raise HTTPException(status_code=502, detail="Could not fetch Google Calendar list.") from exc

    calendars = []
    for item in response.get("items", []):
        calendars.append(
            {
                "id": item.get("id"),
                "summary": item.get("summary"),
                "primary": item.get("primary", False),
                "access_role": item.get("accessRole"),
                "selected": item.get("id") == mapping.google_calendar_id,
            }
        )

    return calendars


@router.post(
    "/mappings",
    response_model=GoogleCalendarIntegrationOut,
    status_code=status.HTTP_201_CREATED,
)
def create_google_calendar_mapping(
    payload: GoogleCalendarIntegrationCreate,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    clinic_id = _resolve_current_clinic_id_or_403(db, current_user)
    _ensure_google_calendar_manage_access(db, current_user, clinic_id)

    _ensure_provider_belongs_to_clinic(db, payload.provider_id, clinic_id)
    _ensure_doctor_belongs_to_provider(
        db,
        provider_id=payload.provider_id,
        doctor_id=payload.doctor_id,
    )

    existing = (
        db.query(models.GoogleCalendarIntegration)
        .filter(
            models.GoogleCalendarIntegration.clinic_id == clinic_id,
            models.GoogleCalendarIntegration.provider_id == payload.provider_id,
            models.GoogleCalendarIntegration.doctor_id == payload.doctor_id,
            models.GoogleCalendarIntegration.google_calendar_id == payload.google_calendar_id,
        )
        .first()
    )
    if existing:
        raise HTTPException(
            status_code=409,
            detail="This Google Calendar mapping already exists.",
        )

    mapping = models.GoogleCalendarIntegration(
        clinic_id=clinic_id,
        provider_id=payload.provider_id,
        doctor_id=payload.doctor_id,
        google_calendar_id=payload.google_calendar_id.strip(),
        google_calendar_name=payload.google_calendar_name,
        google_account_email=payload.google_account_email,
        sync_direction=payload.sync_direction,
        status="configured",
        is_active=True,
    )

    db.add(mapping)
    db.commit()
    db.refresh(mapping)
    return mapping


@router.patch("/mappings/{mapping_id}", response_model=GoogleCalendarIntegrationOut)
def update_google_calendar_mapping(
    mapping_id: int,
    payload: GoogleCalendarIntegrationUpdate,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    mapping = _get_mapping_or_404(db, mapping_id)
    _ensure_google_calendar_manage_access(db, current_user, mapping.clinic_id)

    data = payload.model_dump(exclude_unset=True)

    if "google_calendar_id" in data and data["google_calendar_id"]:
        data["google_calendar_id"] = data["google_calendar_id"].strip()

    for key, value in data.items():
        setattr(mapping, key, value)

    db.add(mapping)
    db.commit()
    db.refresh(mapping)
    return mapping


@router.delete("/mappings/{mapping_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_google_calendar_mapping(
    mapping_id: int,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    mapping = _get_mapping_or_404(db, mapping_id)
    _ensure_google_calendar_manage_access(db, current_user, mapping.clinic_id)

    db.delete(mapping)
    db.commit()
    return None


@router.post(
    "/mappings/{mapping_id}/freebusy-test",
    response_model=GoogleCalendarFreeBusyTestOut,
)
def test_google_calendar_freebusy(
    mapping_id: int,
    payload: GoogleCalendarFreeBusyTestIn,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    mapping = _get_mapping_or_404(db, mapping_id)
    _ensure_google_calendar_view_access(db, current_user, mapping.clinic_id)

    if not integration_has_usable_tokens(mapping):
        return GoogleCalendarFreeBusyTestOut(
            configured=False,
            calendar_id=mapping.google_calendar_id,
            busy=[],
            message="Calendar mapping exists, but OAuth tokens are not configured yet.",
        )

    busy_raw = query_freebusy(
        mapping,
        time_min=payload.time_min,
        time_max=payload.time_max,
    )

    busy = []
    for item in busy_raw:
        if item.get("start") and item.get("end"):
            busy.append(
                {
                    "start": item["start"],
                    "end": item["end"],
                }
            )

    return GoogleCalendarFreeBusyTestOut(
        configured=True,
        calendar_id=mapping.google_calendar_id,
        busy=busy,
        message="FreeBusy query completed.",
    )