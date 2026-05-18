# Path: backend/main.py

import os

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

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