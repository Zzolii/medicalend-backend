# Path: backend/main.py

import os
import time
from collections import defaultdict, deque
from typing import Deque, Dict, Tuple

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app import models  # noqa: F401
from app.api.v1.admin import router as admin_router
from app.api.v1.appointments import router as appointments_router
from app.api.v1.auth import router as auth_router
from app.api.v1.billing import router as billing_router
from app.api.v1.care_episodes import router as care_episodes_router
from app.api.v1.dashboard import router as dashboard_router
from app.api.v1.documents import router as documents_router
from app.api.v1.google_calendar import router as google_calendar_router
from app.api.v1.patient_portal import router as patient_portal_router
from app.api.v1.patients import router as patients_router
from app.api.v1.provider_availability import router as provider_availability_router
from app.api.v1.provider_free_slots import router as provider_free_slots_router
from app.api.v1.provider_structure import router as provider_structure_router
from app.api.v1.providers import router as providers_router
from app.api.v1.referrals import router as referrals_router
from app.api.v1.subscriptions import router as subscriptions_router
from app.api.v1.users import router as users_router
from app.core.config import settings
from app.models.google_calendar_integration import GoogleCalendarIntegration  # noqa: F401
from app.models.medical_document import MedicalDocument  # noqa: F401

os.makedirs("uploads/documents", exist_ok=True)
os.makedirs("uploads/provider-images", exist_ok=True)

app = FastAPI(
    title=settings.PROJECT_NAME,
    version="0.1.0",
    docs_url="/docs" if settings.api_docs_enabled else None,
    redoc_url="/redoc" if settings.api_docs_enabled else None,
    openapi_url="/openapi.json" if settings.api_docs_enabled else None,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type", "Accept", "Origin"],
)

RateLimitKey = Tuple[str, str]
rate_limit_store: Dict[RateLimitKey, Deque[float]] = defaultdict(deque)


def _client_ip(request: Request) -> str:
    forwarded_for = request.headers.get("x-forwarded-for")
    if forwarded_for:
        return forwarded_for.split(",")[0].strip()

    real_ip = request.headers.get("x-real-ip")
    if real_ip:
        return real_ip.strip()

    if request.client and request.client.host:
        return request.client.host

    return "unknown"


def _rate_limit_bucket(path: str, method: str) -> tuple[str, int]:
    normalized_path = path.rstrip("/") or "/"
    normalized_method = method.upper()

    if normalized_method == "OPTIONS":
        return "preflight", settings.RATE_LIMIT_GENERAL_PER_MINUTE * 2

    if normalized_path.endswith("/auth/login"):
        return "auth-login", settings.RATE_LIMIT_AUTH_PER_MINUTE

    if normalized_path.endswith("/auth/forgot-password"):
        return "auth-password-reset", settings.RATE_LIMIT_PASSWORD_RESET_PER_MINUTE

    if normalized_path.endswith("/auth/resend-verification"):
        return "auth-resend-verification", settings.RATE_LIMIT_PASSWORD_RESET_PER_MINUTE

    if normalized_method == "POST" and "/documents" in normalized_path:
        return "document-upload", settings.RATE_LIMIT_UPLOAD_PER_MINUTE

    return "general", settings.RATE_LIMIT_GENERAL_PER_MINUTE


@app.middleware("http")
async def rate_limit_middleware(request: Request, call_next):
    if not settings.ENABLE_RATE_LIMITING:
        return await call_next(request)

    bucket, limit = _rate_limit_bucket(request.url.path, request.method)

    if bucket == "preflight":
        return await call_next(request)

    now = time.time()
    window_start = now - 60
    ip = _client_ip(request)
    key = (ip, bucket)

    requests = rate_limit_store[key]

    while requests and requests[0] < window_start:
        requests.popleft()

    if len(requests) >= limit:
        return JSONResponse(
            status_code=429,
            content={
                "detail": "Too many requests. Please try again later.",
                "bucket": bucket,
            },
            headers={"Retry-After": "60"},
        )

    requests.append(now)

    if len(rate_limit_store) > 10000:
        stale_keys = [
            stored_key
            for stored_key, timestamps in rate_limit_store.items()
            if not timestamps or timestamps[-1] < window_start
        ]
        for stale_key in stale_keys[:1000]:
            rate_limit_store.pop(stale_key, None)

    return await call_next(request)


@app.get("/")
def read_root():
    return {"message": "MediCalend API is running"}


app.include_router(auth_router, prefix=settings.API_V1_PREFIX)
app.include_router(users_router, prefix=settings.API_V1_PREFIX)
app.include_router(patients_router, prefix=settings.API_V1_PREFIX)
app.include_router(appointments_router, prefix=settings.API_V1_PREFIX)
app.include_router(care_episodes_router, prefix=settings.API_V1_PREFIX)
app.include_router(referrals_router, prefix=settings.API_V1_PREFIX)
app.include_router(dashboard_router, prefix=settings.API_V1_PREFIX)
app.include_router(patient_portal_router, prefix=settings.API_V1_PREFIX)
app.include_router(admin_router, prefix=settings.API_V1_PREFIX)
app.include_router(documents_router, prefix=settings.API_V1_PREFIX)
app.include_router(provider_availability_router, prefix=settings.API_V1_PREFIX)
app.include_router(provider_free_slots_router, prefix=settings.API_V1_PREFIX)
app.include_router(provider_structure_router, prefix=settings.API_V1_PREFIX)
app.include_router(providers_router, prefix=settings.API_V1_PREFIX)
app.include_router(subscriptions_router, prefix=settings.API_V1_PREFIX)
app.include_router(billing_router, prefix=settings.API_V1_PREFIX)
app.include_router(google_calendar_router, prefix=settings.API_V1_PREFIX)