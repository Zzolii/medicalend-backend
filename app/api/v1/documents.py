# Path: backend/app/api/v1/documents.py

from pathlib import Path
from typing import List, Optional
from uuid import uuid4

from fastapi import (
    APIRouter,
    Depends,
    File,
    Form,
    HTTPException,
    Request,
    UploadFile,
    status,
)
from sqlalchemy import or_
from sqlalchemy.orm import Session

from app import models
from app.core.security import get_current_provider_for_user, get_current_user
from app.db import get_db
from app.schemas.medical_document import MedicalDocumentOut

router = APIRouter(prefix="/documents", tags=["documents"])

UPLOAD_DIR = Path("uploads/documents")
ALLOWED_MIME_TYPES = {"application/pdf"}
STAFF_ROLES = {"clinic_admin", "doctor", "assistant", "reception", "receptionist"}
REFERRAL_ACCESS_STATUSES = {"pending", "accepted", "in_progress", "completed"}


def _normalize_clinic_role(value: Optional[str]) -> Optional[str]:
    if value == "receptionist":
        return "reception"
    return value


def _get_my_patient_profile(db: Session, current_user):
    patient = (
        db.query(models.Patient)
        .filter(models.Patient.user_id == current_user.id)
        .first()
    )
    if not patient:
        raise HTTPException(
            status_code=404,
            detail="Patient profile not linked to this user",
        )
    return patient


def _get_accessible_clinic_ids(db: Session, current_user) -> List[int]:
    memberships = (
        db.query(models.ClinicMembership)
        .filter(
            models.ClinicMembership.user_id == current_user.id,
            models.ClinicMembership.is_active == True,  # noqa: E712
        )
        .all()
    )

    clinic_ids: List[int] = []
    for membership in memberships:
        role = _normalize_clinic_role(getattr(membership, "role", None))
        clinic_id = getattr(membership, "clinic_id", None)
        if role in STAFF_ROLES and clinic_id is not None and clinic_id not in clinic_ids:
            clinic_ids.append(clinic_id)

    return clinic_ids


def _ensure_episode_exists(db: Session, episode_id: int):
    episode = (
        db.query(models.CareEpisode)
        .filter(models.CareEpisode.id == episode_id)
        .first()
    )
    if not episode:
        raise HTTPException(status_code=404, detail="Care episode not found")
    return episode


def _ensure_appointment_exists(db: Session, appointment_id: int):
    appointment = (
        db.query(models.Appointment)
        .filter(models.Appointment.id == appointment_id)
        .first()
    )
    if not appointment:
        raise HTTPException(status_code=404, detail="Appointment not found")
    return appointment


def _ensure_document_exists(db: Session, document_id: int):
    doc = (
        db.query(models.MedicalDocument)
        .filter(models.MedicalDocument.id == document_id)
        .first()
    )
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
    return doc


def _ensure_appointment_matches_episode(
    db: Session,
    episode_id: int,
    appointment_id: Optional[int],
):
    if appointment_id is None:
        return None

    appointment = _ensure_appointment_exists(db, appointment_id)

    if appointment.episode_id != episode_id:
        raise HTTPException(
            status_code=400,
            detail="Appointment does not belong to the selected episode",
        )

    return appointment


def _clinic_staff_can_access_episode(db: Session, episode, clinic_ids: List[int]) -> bool:
    if not clinic_ids:
        return False

    owner_provider = (
        db.query(models.Provider)
        .filter(models.Provider.id == episode.owner_provider_id)
        .first()
    )
    if owner_provider and getattr(owner_provider, "clinic_id", None) in clinic_ids:
        return True

    referral_provider_ids = (
        db.query(models.Referral.to_provider_id)
        .filter(
            models.Referral.episode_id == episode.id,
            models.Referral.status.in_(REFERRAL_ACCESS_STATUSES),
        )
        .all()
    )
    referral_provider_ids += (
        db.query(models.Referral.from_provider_id)
        .filter(
            models.Referral.episode_id == episode.id,
            models.Referral.status.in_(REFERRAL_ACCESS_STATUSES),
        )
        .all()
    )

    provider_ids = []
    for row in referral_provider_ids:
        pid = row[0]
        if pid is not None and pid not in provider_ids:
            provider_ids.append(pid)

    if provider_ids:
        matched_provider = (
            db.query(models.Provider)
            .filter(
                models.Provider.id.in_(provider_ids),
                models.Provider.clinic_id.in_(clinic_ids),
            )
            .first()
        )
        if matched_provider is not None:
            return True

    appointment_match = (
        db.query(models.Appointment)
        .filter(
            models.Appointment.episode_id == episode.id,
            or_(
                models.Appointment.clinic_id.in_(clinic_ids),
                models.Appointment.provider_id.in_(
                    db.query(models.Provider.id).filter(
                        models.Provider.clinic_id.in_(clinic_ids)
                    )
                ),
            ),
        )
        .first()
    )
    return appointment_match is not None


def _provider_can_access_episode(db: Session, current_user, episode) -> bool:
    try:
        my_provider = get_current_provider_for_user(db, current_user)
    except HTTPException:
        return False

    if episode.owner_provider_id == my_provider.id:
        return True

    referral = (
        db.query(models.Referral)
        .filter(
            models.Referral.episode_id == episode.id,
            models.Referral.status.in_(REFERRAL_ACCESS_STATUSES),
            or_(
                models.Referral.to_provider_id == my_provider.id,
                models.Referral.from_provider_id == my_provider.id,
            ),
        )
        .first()
    )
    if referral is not None:
        return True

    appointment = (
        db.query(models.Appointment)
        .filter(
            models.Appointment.episode_id == episode.id,
            models.Appointment.provider_id == my_provider.id,
        )
        .first()
    )
    return appointment is not None


def _ensure_episode_access(db: Session, current_user, episode) -> None:
    if current_user.role == "admin":
        return

    if current_user.role == "patient":
        patient = _get_my_patient_profile(db, current_user)
        if episode.patient_id != patient.id:
            raise HTTPException(status_code=403, detail="Not allowed")
        return

    clinic_ids = _get_accessible_clinic_ids(db, current_user)
    if _clinic_staff_can_access_episode(db, episode, clinic_ids):
        return

    if _provider_can_access_episode(db, current_user, episode):
        return

    raise HTTPException(status_code=403, detail="Not allowed")


def _ensure_appointment_access(db: Session, current_user, appointment) -> None:
    if current_user.role == "admin":
        return

    if current_user.role == "patient":
        patient = _get_my_patient_profile(db, current_user)
        if appointment.patient_id != patient.id:
            raise HTTPException(status_code=403, detail="Not allowed")
        return

    clinic_ids = _get_accessible_clinic_ids(db, current_user)
    if clinic_ids:
        provider = None
        provider_clinic_id = None

        if appointment.provider_id is not None:
            provider = (
                db.query(models.Provider)
                .filter(models.Provider.id == appointment.provider_id)
                .first()
            )
            provider_clinic_id = getattr(provider, "clinic_id", None) if provider else None

        appointment_clinic_id = getattr(appointment, "clinic_id", None)
        if appointment_clinic_id in clinic_ids or provider_clinic_id in clinic_ids:
            return

    if current_user.role == "provider":
        try:
            my_provider = get_current_provider_for_user(db, current_user)
        except HTTPException:
            my_provider = None

        if my_provider:
            if appointment.provider_id == my_provider.id:
                return

            if appointment.episode_id is not None:
                episode = _ensure_episode_exists(db, appointment.episode_id)
                if _provider_can_access_episode(db, current_user, episode):
                    return

    raise HTTPException(status_code=403, detail="Not allowed")


def _resolve_episode_and_appointment(
    db: Session,
    *,
    episode_id: Optional[int],
    appointment_id: Optional[int],
):
    appointment = None
    episode = None

    if appointment_id is not None:
        appointment = _ensure_appointment_exists(db, appointment_id)

    if episode_id is not None:
        episode = _ensure_episode_exists(db, episode_id)

    if appointment and episode:
        if appointment.episode_id != episode.id:
            raise HTTPException(
                status_code=400,
                detail="Appointment does not belong to the selected episode",
            )
        return episode, appointment

    if appointment and not episode:
        if appointment.episode_id is None:
            raise HTTPException(
                status_code=400,
                detail="Appointment is not linked to any episode",
            )
        episode = _ensure_episode_exists(db, appointment.episode_id)
        return episode, appointment

    if episode and not appointment:
        return episode, None

    raise HTTPException(
        status_code=400,
        detail="episode_id or appointment_id is required",
    )


def _save_upload(file: UploadFile) -> str:
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

    ext = Path(file.filename or "").suffix.lower()
    if ext != ".pdf":
        ext = ".pdf"

    stored_name = f"{uuid4().hex}{ext}"
    destination = UPLOAD_DIR / stored_name

    with destination.open("wb") as out:
        while True:
            chunk = file.file.read(1024 * 1024)
            if not chunk:
                break
            out.write(chunk)

    return stored_name


def _create_document_record(
    db: Session,
    request: Request,
    *,
    current_user,
    episode,
    appointment,
    file: UploadFile,
):
    if file.content_type not in ALLOWED_MIME_TYPES:
        raise HTTPException(
            status_code=400,
            detail="Only PDF files are allowed",
        )

    _ensure_episode_access(db, current_user, episode)
    if appointment is not None:
        _ensure_appointment_access(db, current_user, appointment)

    original_name = (file.filename or "").strip() or "document.pdf"
    stored_name = _save_upload(file)

    base_url = str(request.base_url).rstrip("/")
    file_url = f"{base_url}/uploads/documents/{stored_name}"

    doc = models.MedicalDocument(
        episode_id=episode.id,
        appointment_id=appointment.id if appointment else None,
        uploaded_by_user_id=current_user.id,
        file_name=original_name,
        stored_name=stored_name,
        file_url=file_url,
        mime_type="application/pdf",
    )
    db.add(doc)
    db.commit()
    db.refresh(doc)
    return doc


@router.post("/upload", response_model=MedicalDocumentOut, status_code=status.HTTP_201_CREATED)
def upload_document(
    request: Request,
    episode_id: Optional[int] = Form(None),
    appointment_id: Optional[int] = Form(None),
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    episode, appointment = _resolve_episode_and_appointment(
        db,
        episode_id=episode_id,
        appointment_id=appointment_id,
    )

    return _create_document_record(
        db,
        request,
        current_user=current_user,
        episode=episode,
        appointment=appointment,
        file=file,
    )


@router.get("/{document_id}", response_model=MedicalDocumentOut)
def get_document(
    document_id: int,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    doc = _ensure_document_exists(db, document_id)

    episode = _ensure_episode_exists(db, doc.episode_id)
    _ensure_episode_access(db, current_user, episode)

    if doc.appointment_id is not None:
        appointment = _ensure_appointment_exists(db, doc.appointment_id)
        _ensure_appointment_access(db, current_user, appointment)

    return doc


@router.post(
    "/care-episodes/{episode_id}/documents",
    response_model=MedicalDocumentOut,
    status_code=status.HTTP_201_CREATED,
)
def upload_document_for_episode(
    episode_id: int,
    request: Request,
    file: UploadFile = File(...),
    title: Optional[str] = Form(None),
    appointment_id: Optional[int] = Form(None),
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    episode = _ensure_episode_exists(db, episode_id)
    appointment = _ensure_appointment_matches_episode(
        db,
        episode_id=episode_id,
        appointment_id=appointment_id,
    )

    doc = _create_document_record(
        db,
        request,
        current_user=current_user,
        episode=episode,
        appointment=appointment,
        file=file,
    )

    if title and title.strip():
        safe_title = title.strip()
        if hasattr(doc, "title"):
            setattr(doc, "title", safe_title)
            db.add(doc)
            db.commit()
            db.refresh(doc)

    return doc


@router.get("/episodes/{episode_id}", response_model=List[MedicalDocumentOut])
def list_episode_documents(
    episode_id: int,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    episode = _ensure_episode_exists(db, episode_id)
    _ensure_episode_access(db, current_user, episode)

    rows = (
        db.query(models.MedicalDocument)
        .filter(models.MedicalDocument.episode_id == episode_id)
        .order_by(
            models.MedicalDocument.created_at.desc(),
            models.MedicalDocument.id.desc(),
        )
        .all()
    )
    return rows


@router.get(
    "/care-episodes/{episode_id}/documents",
    response_model=List[MedicalDocumentOut],
)
def list_documents_for_episode_alias(
    episode_id: int,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    episode = _ensure_episode_exists(db, episode_id)
    _ensure_episode_access(db, current_user, episode)

    rows = (
        db.query(models.MedicalDocument)
        .filter(models.MedicalDocument.episode_id == episode_id)
        .order_by(
            models.MedicalDocument.created_at.desc(),
            models.MedicalDocument.id.desc(),
        )
        .all()
    )
    return rows


@router.get("/appointments/{appointment_id}", response_model=List[MedicalDocumentOut])
def list_appointment_documents(
    appointment_id: int,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    appointment = _ensure_appointment_exists(db, appointment_id)
    _ensure_appointment_access(db, current_user, appointment)

    rows = (
        db.query(models.MedicalDocument)
        .filter(models.MedicalDocument.appointment_id == appointment_id)
        .order_by(
            models.MedicalDocument.created_at.desc(),
            models.MedicalDocument.id.desc(),
        )
        .all()
    )
    return rows