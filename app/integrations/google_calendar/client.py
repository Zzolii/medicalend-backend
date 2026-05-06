# Path: backend/app/integrations/google_calendar/client.py

from datetime import datetime
from typing import Any, Optional

from fastapi import HTTPException

try:
    from google.oauth2.credentials import Credentials
    from googleapiclient.discovery import build
except Exception:
    Credentials = None
    build = None


CALENDAR_SCOPES = [
    "https://www.googleapis.com/auth/calendar.events",
    "https://www.googleapis.com/auth/calendar.freebusy",
]


def _ensure_google_dependencies_available() -> None:
    if Credentials is None or build is None:
        raise HTTPException(
            status_code=500,
            detail="Google Calendar dependencies are not installed. Add google-auth and google-api-python-client.",
        )


def integration_has_usable_tokens(integration) -> bool:
    return bool(
        getattr(integration, "access_token", None)
        and getattr(integration, "refresh_token", None)
        and getattr(integration, "client_id", None)
        and getattr(integration, "client_secret", None)
    )


def build_calendar_service(integration):
    _ensure_google_dependencies_available()

    if not integration_has_usable_tokens(integration):
        raise HTTPException(
            status_code=400,
            detail="Google Calendar OAuth tokens are not configured for this calendar mapping.",
        )

    scopes_raw = getattr(integration, "scopes", None)
    scopes = [item.strip() for item in scopes_raw.split(",")] if scopes_raw else CALENDAR_SCOPES

    credentials = Credentials(
        token=integration.access_token,
        refresh_token=integration.refresh_token,
        token_uri=integration.token_uri or "https://oauth2.googleapis.com/token",
        client_id=integration.client_id,
        client_secret=integration.client_secret,
        scopes=scopes,
    )

    return build("calendar", "v3", credentials=credentials)


def query_freebusy(
    integration,
    *,
    time_min: datetime,
    time_max: datetime,
) -> list[dict[str, Any]]:
    service = build_calendar_service(integration)

    body = {
        "timeMin": time_min.isoformat(),
        "timeMax": time_max.isoformat(),
        "items": [{"id": integration.google_calendar_id}],
    }

    response = service.freebusy().query(body=body).execute()
    calendars = response.get("calendars", {})
    calendar_data = calendars.get(integration.google_calendar_id, {})
    return calendar_data.get("busy", [])


def create_calendar_event(
    integration,
    *,
    summary: str,
    description: Optional[str],
    start_time: datetime,
    end_time: datetime,
    timezone_name: str = "Europe/Bucharest",
) -> dict[str, Any]:
    service = build_calendar_service(integration)

    body = {
        "summary": summary,
        "description": description or "",
        "start": {
            "dateTime": start_time.isoformat(),
            "timeZone": timezone_name,
        },
        "end": {
            "dateTime": end_time.isoformat(),
            "timeZone": timezone_name,
        },
        "extendedProperties": {
            "private": {
                "source": "MediCalend",
                "provider_id": str(getattr(integration, "provider_id", "")),
                "doctor_id": str(getattr(integration, "doctor_id", "") or ""),
                "clinic_id": str(getattr(integration, "clinic_id", "")),
            }
        },
    }

    return (
        service.events()
        .insert(calendarId=integration.google_calendar_id, body=body)
        .execute()
    )