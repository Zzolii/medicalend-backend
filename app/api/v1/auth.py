# Path: backend/app/api/v1/auth.py

from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import quote
from uuid import uuid4

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from sqlalchemy import func
from sqlalchemy.orm import Session

from app import models
from app.core.config import settings
from app.core.security import (
    create_access_token,
    create_action_token,
    decode_action_token,
    hash_password,
    verify_password,
)
from app.db import get_db
from app.schemas.auth import (
    ForgotPasswordRequest,
    LoginRequest,
    MessageResponse,
    ResendVerificationRequest,
    ResetPasswordRequest,
    TokenResponse,
    VerifyEmailRequest,
)
from app.schemas.patient import Patient as PatientOut
from app.schemas.provider import Provider as ProviderOut
from app.schemas.register import RegisterPatientRequest, RegisterProviderRequest
from app.schemas.user import User as UserOut, UserCreate
from app.utils.mail import send_email

router = APIRouter(prefix="/auth", tags=["auth"])

UPLOAD_DIR = Path("uploads/provider-images")
ALLOWED_IMAGE_TYPES = {
    "image/jpeg": ".jpg",
    "image/jpg": ".jpg",
    "image/png": ".png",
    "image/webp": ".webp",
    "image/heic": ".heic",
}


def _normalize_email(email: str) -> str:
    return (email or "").strip().lower()


def _clean_optional_text(value: str | None) -> str | None:
    if value is None:
        return None
    cleaned = " ".join(value.strip().split())
    return cleaned or None


def _slugify_clinic_name(name: str) -> str:
    base = (name or "").strip().lower()
    if not base:
        return "clinic"

    allowed = []
    prev_dash = False

    for ch in base:
        if ch.isalnum():
            allowed.append(ch)
            prev_dash = False
        else:
            if not prev_dash:
                allowed.append("-")
                prev_dash = True

    slug = "".join(allowed).strip("-")
    return slug or "clinic"


def _ensure_unique_clinic_slug(db: Session, raw_slug: str) -> str:
    slug = raw_slug
    counter = 2

    while db.query(models.Clinic).filter(models.Clinic.slug == slug).first():
        slug = f"{raw_slug}-{counter}"
        counter += 1

    return slug


def _build_verify_email_url(token: str) -> str:
    return f"{settings.FRONTEND_VERIFY_EMAIL_URL}?token={quote(token)}"


def _build_reset_password_url(token: str) -> str:
    return f"{settings.FRONTEND_RESET_PASSWORD_URL}?token={quote(token)}"


def _public_upload_url(filename: str) -> str:
    return f"/uploads/provider-images/{filename}"


def _find_user_by_normalized_email(db: Session, email: str):
    normalized_email = _normalize_email(email)
    return (
        db.query(models.User)
        .filter(func.lower(func.trim(models.User.email)) == normalized_email)
        .first()
    )


def _save_provider_image(image_file: UploadFile | None) -> str | None:
    if not image_file or not image_file.filename:
        return None

    content_type = (image_file.content_type or "").lower().strip()
    extension = ALLOWED_IMAGE_TYPES.get(content_type)

    if not extension:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Tip de imagine invalid. Sunt permise JPG, PNG, WEBP sau HEIC.",
        )

    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

    safe_name = f"{uuid4().hex}{extension}"
    file_path = UPLOAD_DIR / safe_name

    with file_path.open("wb") as buffer:
        while True:
            chunk = image_file.file.read(1024 * 1024)
            if not chunk:
                break
            buffer.write(chunk)

    return _public_upload_url(safe_name)


def _send_verification_email(user: models.User) -> None:
    token = create_action_token(
        subject=str(user.id),
        purpose="verify_email",
        expires_delta=timedelta(hours=settings.EMAIL_VERIFY_TOKEN_EXPIRE_HOURS),
    )
    verify_url = _build_verify_email_url(token)

    subject = "Confirmă adresa de e-mail – MediCalend"
    text_body = (
        "Bun venit în MediCalend.\n\n"
        "Pentru a-ți confirma contul, accesează linkul de mai jos:\n"
        f"{verify_url}\n\n"
        f"Linkul expiră în {settings.EMAIL_VERIFY_TOKEN_EXPIRE_HOURS} ore."
    )
    html_body = f"""
    <html>
      <body>
        <p>Bun venit în <strong>MediCalend</strong>.</p>
        <p>Pentru a-ți confirma contul, apasă pe linkul de mai jos:</p>
        <p><a href="{verify_url}">Confirmă e-mailul</a></p>
        <p>Dacă butonul nu funcționează, copiază acest link în browser:</p>
        <p><a href="{verify_url}">{verify_url}</a></p>
        <p>Linkul expiră în {settings.EMAIL_VERIFY_TOKEN_EXPIRE_HOURS} ore.</p>
      </body>
    </html>
    """
    send_email(user.email, subject, text_body, html_body)


def _send_reset_password_email(user: models.User) -> None:
    token = create_action_token(
        subject=str(user.id),
        purpose="reset_password",
        expires_delta=timedelta(minutes=settings.PASSWORD_RESET_TOKEN_EXPIRE_MINUTES),
    )
    reset_url = _build_reset_password_url(token)

    subject = "Resetare parolă – MediCalend"
    text_body = (
        "Am primit o cerere de resetare a parolei pentru contul tău MediCalend.\n\n"
        "Accesează linkul de mai jos pentru a seta o parolă nouă:\n"
        f"{reset_url}\n\n"
        f"Linkul expiră în {settings.PASSWORD_RESET_TOKEN_EXPIRE_MINUTES} minute.\n"
        "Dacă nu ai cerut resetarea parolei, poți ignora acest mesaj."
    )
    html_body = f"""
    <html>
      <body>
        <p>Am primit o cerere de resetare a parolei pentru contul tău <strong>MediCalend</strong>.</p>
        <p>Apasă pe linkul de mai jos pentru a seta o parolă nouă:</p>
        <p><a href="{reset_url}">Resetează parola</a></p>
        <p>Dacă butonul nu funcționează, copiază acest link în browser:</p>
        <p><a href="{reset_url}">{reset_url}</a></p>
        <p>Linkul expiră în {settings.PASSWORD_RESET_TOKEN_EXPIRE_MINUTES} minute.</p>
        <p>Dacă nu ai cerut resetarea parolei, poți ignora acest mesaj.</p>
      </body>
    </html>
    """
    send_email(user.email, subject, text_body, html_body)


# Path: backend/app/api/v1/auth.py

def _ensure_provider_login_allowed(db: Session, user: models.User) -> None:
    provider = (
        db.query(models.Provider)
        .filter(models.Provider.user_id == user.id)
        .first()
    )

    if provider:
        if getattr(provider, "status", None) != "approved":
            print(
                "[AUTH LOGIN] provider not approved "
                f"user_id={user.id} provider_id={provider.id} status={getattr(provider, 'status', None)}"
            )
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Contul clinicii așteaptă aprobarea administratorului.",
            )

        if getattr(provider, "is_active", True) is False:
            print(
                f"[AUTH LOGIN] provider inactive user_id={user.id} provider_id={provider.id}"
            )
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Profilul clinicii este inactiv.",
            )

        return

    membership = (
        db.query(models.ClinicMembership)
        .filter(
            models.ClinicMembership.user_id == user.id,
            models.ClinicMembership.is_active == True,  # noqa: E712
        )
        .first()
    )

    if not membership:
        print(
            f"[AUTH LOGIN] no provider profile or active clinic membership user_id={user.id} email={user.email}"
        )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Contul nu este asociat cu o clinică activă.",
        )

    clinic = (
        db.query(models.Clinic)
        .filter(models.Clinic.id == membership.clinic_id)
        .first()
    )

    if not clinic or getattr(clinic, "is_active", True) is False:
        print(
            f"[AUTH LOGIN] inactive clinic membership user_id={user.id} clinic_id={membership.clinic_id}"
        )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Clinica asociată contului este inactivă.",
        )

    approved_clinic_provider = (
        db.query(models.Provider)
        .filter(
            models.Provider.clinic_id == membership.clinic_id,
            models.Provider.status == "approved",
            models.Provider.is_active == True,  # noqa: E712
        )
        .first()
    )

    if not approved_clinic_provider:
        print(
            f"[AUTH LOGIN] clinic has no approved provider user_id={user.id} clinic_id={membership.clinic_id}"
        )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Clinica asociată contului nu este încă aprobată.",
        )

    if user.is_active is False:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Cont inactiv",
        )


def _create_provider_record(
    *,
    db: Session,
    email: str,
    password: str,
    name: str,
    provider_type: str,
    website: str | None,
    image_url: str | None,
    public_description: str | None,
    specialty: str | None,
    services_offered: str | None,
    cui: str,
    trade_register_number: str | None,
    contact_person_name: str,
    contact_email: str,
    contact_phone: str,
    phone: str | None,
    address_line: str,
    city: str,
    county: str,
    postal_code: str | None,
    country: str | None,
    coverage_area: str | None,
    sanitary_authorization_number: str,
    sanitary_authorization_expires_at,
    healthcare_compliance_confirmed: bool,
    provider_agreement_accepted: bool,
):
    normalized_email = _normalize_email(email)
    normalized_contact_email = _normalize_email(contact_email)
    normalized_country = (country or "RO").strip().upper()

    existing_user = _find_user_by_normalized_email(db, normalized_email)
    if existing_user:
        raise HTTPException(status_code=409, detail="Email already registered")

    existing_cui = db.query(models.Provider).filter(models.Provider.cui == cui).first()
    if existing_cui:
        raise HTTPException(status_code=409, detail="CUI already registered")

    if trade_register_number:
        existing_trade_register = (
            db.query(models.Provider)
            .filter(models.Provider.trade_register_number == trade_register_number)
            .first()
        )
        if existing_trade_register:
            raise HTTPException(
                status_code=409,
                detail="Trade register number already registered",
            )

    if not healthcare_compliance_confirmed:
        raise HTTPException(
            status_code=400,
            detail="Healthcare compliance confirmation is required",
        )

    if not provider_agreement_accepted:
        raise HTTPException(
            status_code=400,
            detail="Provider agreement acceptance is required",
        )

    user = models.User(
        email=normalized_email,
        hashed_password=hash_password(password),
        role="provider",
        is_active=True,
        is_email_verified=False,
        email_verified_at=None,
    )
    db.add(user)
    db.flush()

    clinic_slug_base = _slugify_clinic_name(name)
    clinic_slug = _ensure_unique_clinic_slug(db, clinic_slug_base)

    clinic = models.Clinic(
        name=name,
        slug=clinic_slug,
        phone=contact_phone or phone,
        email=normalized_contact_email,
        address_line=address_line,
        city=city,
        county=county,
        postal_code=postal_code,
        country=normalized_country,
        is_active=True,
    )
    db.add(clinic)
    db.flush()

    membership = models.ClinicMembership(
        user_id=user.id,
        clinic_id=clinic.id,
        role="clinic_admin",
        is_active=True,
    )
    db.add(membership)
    db.flush()

    provider = models.Provider(
        user_id=user.id,
        clinic_id=clinic.id,
        name=name,
        provider_type=provider_type,
        website=website,
        image_url=image_url,
        public_description=public_description,
        specialty=specialty,
        services_offered=services_offered,
        cui=cui,
        trade_register_number=trade_register_number,
        contact_person_name=contact_person_name,
        contact_email=normalized_contact_email,
        contact_phone=contact_phone,
        phone=phone or contact_phone,
        email=normalized_contact_email,
        address_line=address_line,
        city=city,
        county=county,
        postal_code=postal_code,
        country=normalized_country,
        coverage_area=coverage_area,
        sanitary_authorization_number=sanitary_authorization_number,
        sanitary_authorization_expires_at=sanitary_authorization_expires_at,
        healthcare_compliance_confirmed=healthcare_compliance_confirmed,
        provider_agreement_accepted=provider_agreement_accepted,
        is_active=True,
        status="pending",
        rejection_reason=None,
    )
    db.add(provider)

    db.commit()
    db.refresh(provider)

    return provider


@router.post("/login", response_model=TokenResponse)
def login(payload: LoginRequest, db: Session = Depends(get_db)):
    normalized_email = _normalize_email(str(payload.email))

    user = _find_user_by_normalized_email(db, normalized_email)

    if not user:
        print(f"[AUTH LOGIN] user not found for email={normalized_email}")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Credentiale invalide",
        )

    password_ok = verify_password(payload.password, user.hashed_password)
    if not password_ok:
        print(f"[AUTH LOGIN] password mismatch for user_id={user.id} email={user.email}")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Credentiale invalide",
        )

    if not user.is_active:
        print(f"[AUTH LOGIN] inactive user user_id={user.id} email={user.email}")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Cont inactiv",
        )

    if user.role == "patient" and not user.is_email_verified:
        print(f"[AUTH LOGIN] patient email not verified user_id={user.id} email={user.email}")
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="E-mailul nu a fost confirmat încă",
        )

    if user.role == "provider":
        _ensure_provider_login_allowed(db, user)

    token = create_access_token(subject=str(user.id))
    return {"access_token": token, "token_type": "bearer"}


@router.post("/bootstrap-admin", response_model=UserOut)
def bootstrap_admin(payload: UserCreate, db: Session = Depends(get_db)):
    existing_admin = db.query(models.User).filter(models.User.role == "admin").first()
    if existing_admin:
        raise HTTPException(status_code=409, detail="Admin already exists")

    normalized_email = _normalize_email(payload.email)

    existing = _find_user_by_normalized_email(db, normalized_email)
    if existing:
        raise HTTPException(status_code=409, detail="Email already registered")

    admin = models.User(
        email=normalized_email,
        hashed_password=hash_password(payload.password),
        role="admin",
        is_active=True,
        is_email_verified=True,
        email_verified_at=datetime.now(timezone.utc),
    )
    db.add(admin)
    db.commit()
    db.refresh(admin)
    return admin


@router.post(
    "/register-patient",
    response_model=PatientOut,
    status_code=status.HTTP_201_CREATED,
)
def register_patient(payload: RegisterPatientRequest, db: Session = Depends(get_db)):
    normalized_email = _normalize_email(payload.email)

    existing_user = _find_user_by_normalized_email(db, normalized_email)
    if existing_user:
        raise HTTPException(status_code=409, detail="Email already registered")

    user = models.User(
        email=normalized_email,
        hashed_password=hash_password(payload.password),
        role="patient",
        is_active=True,
        is_email_verified=False,
        email_verified_at=None,
    )
    db.add(user)
    db.commit()
    db.refresh(user)

    patient = models.Patient(
        user_id=user.id,
        first_name=payload.first_name,
        last_name=payload.last_name,
        birth_date=payload.birth_date,
        gender=payload.gender,
        phone=payload.phone,
        email=normalized_email,
        address_line=payload.address_line,
        city=payload.city,
        county=payload.county,
        postal_code=payload.postal_code,
        country=payload.country,
    )
    db.add(patient)
    db.commit()
    db.refresh(patient)

    try:
        _send_verification_email(user)
    except Exception as exc:
        print("[AUTH] verification email send failed:", str(exc))

    return patient


@router.post(
    "/register-provider",
    response_model=ProviderOut,
    status_code=status.HTTP_201_CREATED,
)
def register_provider(payload: RegisterProviderRequest, db: Session = Depends(get_db)):
    return _create_provider_record(
        db=db,
        email=payload.email,
        password=payload.password,
        name=payload.name,
        provider_type=payload.provider_type,
        website=payload.website,
        image_url=payload.image_url,
        public_description=payload.public_description,
        specialty=payload.specialty,
        services_offered=payload.services_offered,
        cui=payload.cui,
        trade_register_number=payload.trade_register_number,
        contact_person_name=payload.contact_person_name,
        contact_email=payload.contact_email,
        contact_phone=payload.contact_phone,
        phone=payload.phone,
        address_line=payload.address_line,
        city=payload.city,
        county=payload.county,
        postal_code=payload.postal_code,
        country=payload.country,
        coverage_area=payload.coverage_area,
        sanitary_authorization_number=payload.sanitary_authorization_number,
        sanitary_authorization_expires_at=payload.sanitary_authorization_expires_at,
        healthcare_compliance_confirmed=payload.healthcare_compliance_confirmed,
        provider_agreement_accepted=payload.provider_agreement_accepted,
    )


@router.post(
    "/register-provider-upload",
    response_model=ProviderOut,
    status_code=status.HTTP_201_CREATED,
)
def register_provider_upload(
    email: str = Form(...),
    password: str = Form(...),
    name: str = Form(...),
    provider_type: str = Form("clinic"),
    website: str | None = Form(None),
    public_description: str | None = Form(None),
    specialty: str | None = Form(None),
    services_offered: str | None = Form(None),
    cui: str = Form(...),
    trade_register_number: str | None = Form(None),
    contact_person_name: str = Form(...),
    contact_email: str = Form(...),
    contact_phone: str = Form(...),
    phone: str | None = Form(None),
    address_line: str = Form(...),
    city: str = Form(...),
    county: str = Form(...),
    postal_code: str | None = Form(None),
    country: str | None = Form("RO"),
    coverage_area: str | None = Form(None),
    sanitary_authorization_number: str = Form(...),
    sanitary_authorization_expires_at: str | None = Form(None),
    healthcare_compliance_confirmed: bool = Form(...),
    provider_agreement_accepted: bool = Form(...),
    image_file: UploadFile | None = File(None),
    db: Session = Depends(get_db),
):
    image_url = _save_provider_image(image_file)

    parsed_expiry = None
    if sanitary_authorization_expires_at:
        try:
            parsed_expiry = datetime.strptime(
                sanitary_authorization_expires_at,
                "%Y-%m-%d",
            ).date()
        except ValueError:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="sanitary_authorization_expires_at trebuie să fie în formatul YYYY-MM-DD",
            )

    return _create_provider_record(
        db=db,
        email=_normalize_email(email),
        password=password,
        name=" ".join(name.strip().split()),
        provider_type=provider_type,
        website=_clean_optional_text(website),
        image_url=image_url,
        public_description=_clean_optional_text(public_description),
        specialty=_clean_optional_text(specialty),
        services_offered=_clean_optional_text(services_offered),
        cui=" ".join(cui.strip().split()),
        trade_register_number=_clean_optional_text(trade_register_number),
        contact_person_name=" ".join(contact_person_name.strip().split()),
        contact_email=_normalize_email(contact_email),
        contact_phone=" ".join(contact_phone.strip().split()),
        phone=_clean_optional_text(phone),
        address_line=" ".join(address_line.strip().split()),
        city=" ".join(city.strip().split()),
        county=" ".join(county.strip().split()),
        postal_code=_clean_optional_text(postal_code),
        country=(country or "RO").strip().upper(),
        coverage_area=_clean_optional_text(coverage_area),
        sanitary_authorization_number=" ".join(
            sanitary_authorization_number.strip().split()
        ),
        sanitary_authorization_expires_at=parsed_expiry,
        healthcare_compliance_confirmed=healthcare_compliance_confirmed,
        provider_agreement_accepted=provider_agreement_accepted,
    )


@router.post("/forgot-password", response_model=MessageResponse)
def forgot_password(payload: ForgotPasswordRequest, db: Session = Depends(get_db)):
    normalized_email = _normalize_email(str(payload.email))
    user = _find_user_by_normalized_email(db, normalized_email)

    if user and user.is_active:
        try:
            _send_reset_password_email(user)
        except Exception as exc:
            print("[AUTH] reset email send failed:", str(exc))

    return {
        "message": "Dacă există un cont asociat acestei adrese, am trimis instrucțiunile de resetare."
    }


@router.post("/reset-password", response_model=MessageResponse)
def reset_password(payload: ResetPasswordRequest, db: Session = Depends(get_db)):
    user_id = decode_action_token(payload.token, "reset_password")
    user = db.query(models.User).filter(models.User.id == user_id).first()

    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    user.hashed_password = hash_password(payload.new_password)
    db.commit()

    return {"message": "Parola a fost resetată cu succes."}


@router.post("/verify-email", response_model=MessageResponse)
def verify_email(payload: VerifyEmailRequest, db: Session = Depends(get_db)):
    user_id = decode_action_token(payload.token, "verify_email")
    user = db.query(models.User).filter(models.User.id == user_id).first()

    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    if not user.is_email_verified:
        user.is_email_verified = True
        user.email_verified_at = datetime.now(timezone.utc)
        db.commit()

    return {"message": "E-mailul a fost confirmat cu succes."}


@router.post("/resend-verification", response_model=MessageResponse)
def resend_verification(payload: ResendVerificationRequest, db: Session = Depends(get_db)):
    normalized_email = _normalize_email(str(payload.email))
    user = _find_user_by_normalized_email(db, normalized_email)

    if user and user.is_active and user.role == "patient" and not user.is_email_verified:
        try:
            _send_verification_email(user)
        except Exception as exc:
            print("[AUTH] verification resend failed:", str(exc))

    return {
        "message": "Dacă există un cont de pacient neverificat asociat acestei adrese, am retrimis e-mailul de confirmare."
    }