# Path: backend/app/api/v1/patient_portal.py

from datetime import datetime, timezone
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from app.schemas.patient import Patient as PatientOut

from app.core.security import get_current_user
from app.db import get_db
from app import models

router = APIRouter(prefix="/patient", tags=["patient"])


def _get_my_patient_profile(db: Session, current_user) -> models.Patient:
    patient = db.query(models.Patient).filter(models.Patient.user_id == current_user.id).first()
    if not patient:
        raise HTTPException(status_code=404, detail="Patient profile not linked to this user")
    return patient


@router.get("/me", response_model=PatientOut)
def read_my_patient_profile(
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    if current_user.role not in ("patient", "admin"):
        raise HTTPException(status_code=403, detail="Not enough permissions")
    return _get_my_patient_profile(db, current_user)



@router.get("/me/dashboard")
def my_dashboard(
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    if current_user.role not in ("patient", "admin"):
        raise HTTPException(status_code=403, detail="Not enough permissions")

    patient = _get_my_patient_profile(db, current_user)

    # Episodes (patienthez kötött)
    episodes = (
        db.query(models.CareEpisode)
        .filter(models.CareEpisode.patient_id == patient.id)
        .order_by(models.CareEpisode.id.desc())
        .all()
    )

    # Upcoming appointments (patienthez kötött, jövő)
    now = datetime.now(timezone.utc)
    upcoming_appointments = (
        db.query(models.Appointment)
        .filter(models.Appointment.patient_id == patient.id)
        .filter(models.Appointment.start_time >= now)
        .order_by(models.Appointment.start_time.asc())
        .limit(10)
        .all()
    )

    return {
        "patient_id": patient.id,
        "episodes": episodes,
        "upcoming_appointments": upcoming_appointments,
    }
