# Path: backend/app/api/v1/api.py

from fastapi import APIRouter

from app.api.v1 import (
    admin,
    appointments,
    auth,
    billing,
    care_episodes,
    dashboard,
    patients,
    providers,
    referrals,
    subscriptions,
    users,
)

api_router = APIRouter()

api_router.include_router(auth.router)
api_router.include_router(users.router)
api_router.include_router(patients.router)
api_router.include_router(providers.router)
api_router.include_router(appointments.router)
api_router.include_router(care_episodes.router)
api_router.include_router(referrals.router)
api_router.include_router(dashboard.router)
api_router.include_router(admin.router)
api_router.include_router(subscriptions.router)
api_router.include_router(billing.router)