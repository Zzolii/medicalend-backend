# Path: backend/app/integrations/google_calendar/oauth.py

from __future__ import annotations

from datetime import timedelta
from urllib.parse import urlencode

from fastapi import HTTPException
from jose import JWTError, jwt

from app.core.config import settings
from app.integrations.google_calendar.client import CALENDAR_SCOPES

GOOGLE_AUTH_BASE_URL = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"


def ensure_google_oauth_configured() -> None:
    if not settings.GOOGLE_CLIENT_ID or not settings.GOOGLE_CLIENT_SECRET:
        raise HTTPException(
            status_code=500,
            detail="Google OAuth is not configured. Missing GOOGLE_CLIENT_ID or GOOGLE_CLIENT_SECRET.",
        )


def create_google_oauth_state(
    *,
    user_id: int,
    clinic_id: int,
    provider_id: int,
    doctor_id: int | None,
) -> str:
    payload = {
        "sub": str(user_id),
        "clinic_id": clinic_id,
        "provider_id": provider_id,
        "doctor_id": doctor_id,
        "typ": "google_oauth_state",
    }

    return jwt.encode(
        payload,
        settings.GOOGLE_OAUTH_STATE_SECRET,
        algorithm=settings.ALGORITHM,
    )


def decode_google_oauth_state(state: str) -> dict:
    try:
        payload = jwt.decode(
            state,
            settings.GOOGLE_OAUTH_STATE_SECRET,
            algorithms=[settings.ALGORITHM],
        )
    except JWTError as exc:
        raise HTTPException(status_code=400, detail="Invalid Google OAuth state.") from exc

    if payload.get("typ") != "google_oauth_state":
        raise HTTPException(status_code=400, detail="Invalid Google OAuth state type.")

    return payload


def build_google_oauth_authorization_url(
    *,
    state: str,
) -> str:
    ensure_google_oauth_configured()

    query = {
        "client_id": settings.GOOGLE_CLIENT_ID,
        "redirect_uri": settings.GOOGLE_OAUTH_REDIRECT_URI,
        "response_type": "code",
        "scope": " ".join(CALENDAR_SCOPES),
        "access_type": "offline",
        "prompt": "consent",
        "include_granted_scopes": "true",
        "state": state,
    }

    return f"{GOOGLE_AUTH_BASE_URL}?{urlencode(query)}"