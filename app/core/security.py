# Path: backend/app/core/security.py

from datetime import datetime, timedelta, timezone
from typing import Callable, Optional

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError, jwt
from passlib.context import CryptContext
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db import get_db


pwd_context = CryptContext(
    schemes=["pbkdf2_sha256", "bcrypt"],
    deprecated="auto",
)
bearer_scheme = HTTPBearer(auto_error=False)


def hash_password(password: str) -> str:
    return pwd_context.hash(password)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    return pwd_context.verify(plain_password, hashed_password)


def create_access_token(subject: str, expires_delta: Optional[timedelta] = None) -> str:
    expire = datetime.now(timezone.utc) + (
        expires_delta or timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    )
    to_encode = {
        "sub": subject,
        "exp": expire,
        "iat": datetime.now(timezone.utc),
        "typ": "access",
    }
    return jwt.encode(to_encode, settings.SECRET_KEY, algorithm=settings.ALGORITHM)


def create_action_token(
    subject: str,
    purpose: str,
    expires_delta: timedelta,
) -> str:
    expire = datetime.now(timezone.utc) + expires_delta
    to_encode = {
        "sub": subject,
        "purpose": purpose,
        "exp": expire,
        "iat": datetime.now(timezone.utc),
        "typ": "action",
    }
    return jwt.encode(to_encode, settings.SECRET_KEY, algorithm=settings.ALGORITHM)


def decode_action_token(token: str, expected_purpose: str) -> int:
    try:
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
        token_type = payload.get("typ")
        purpose = payload.get("purpose")
        sub = payload.get("sub")

        if token_type != "action" or purpose != expected_purpose or not sub:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid or expired token",
            )

        return int(sub)
    except (JWTError, ValueError):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid or expired token",
        )


def get_current_user_id(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(bearer_scheme),
) -> int:
    """
    JWT-ből visszaadja a user_id-t.
    Swaggerben: Authorize → Bearer <token>
    """
    if not credentials:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
        )

    token = credentials.credentials
    try:
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
        sub = payload.get("sub")
        if not sub or payload.get("typ") != "access":
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid token",
            )
        return int(sub)
    except (JWTError, ValueError):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token",
        )


def get_current_user(
    db: Session = Depends(get_db),
    user_id: int = Depends(get_current_user_id),
):
    """
    DB-ből visszaadja a User objektumot.
    """
    from app.models.user import User

    user = db.query(User).filter(User.id == user_id).first()
    if not user or not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found or inactive",
        )
    return user


def require_roles(*allowed_roles: str) -> Callable:
    """
    Globális / legacy role check.
    Példa:
      dependencies=[Depends(require_roles("admin"))]
      dependencies=[Depends(require_roles("admin", "provider"))]
    """
    allowed = set(allowed_roles)

    def _checker(current_user=Depends(get_current_user)):
        role = getattr(current_user, "role", None)
        if role not in allowed:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Not enough permissions",
            )
        return current_user

    return _checker


def get_active_clinic_memberships(
    current_user=Depends(get_current_user),
):
    """
    Visszaadja a user aktív clinic membershipjeit.
    """
    memberships = getattr(current_user, "clinic_memberships", None) or []
    return [m for m in memberships if getattr(m, "is_active", False)]


def get_current_clinic_membership(
    memberships=Depends(get_active_clinic_memberships),
):
    """
    MVP-ben visszaadja az első aktív clinic membershipet.
    Ha több klinika lesz később, ezt active clinic contextre kell cserélni.
    """
    if not memberships:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="User does not belong to a clinic",
        )
    return memberships[0]


def require_clinic_roles(*allowed_clinic_roles: str) -> Callable:
    """
    Clinic-level role check.
    Egyelőre additív, nem váltja ki a legacy users.role mezőt.
    """
    allowed = set(allowed_clinic_roles)

    def _checker(memberships=Depends(get_active_clinic_memberships)):
        for membership in memberships:
            if getattr(membership, "role", None) in allowed and getattr(membership, "is_active", False):
                return membership

        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not enough clinic permissions",
        )

    return _checker


def get_current_provider_for_user(
    db: Session,
    current_user,
):
    """
    Unified provider context:
    1) legacy owner-provider kapcsolat: users.id -> providers.user_id
    2) clinic staff kapcsolat: user -> active clinic_membership -> clinic_id -> provider

    Ez csak a provider kontextust keresi meg.
    A provider státusz / jóváhagyás ellenőrzése a hívó endpoint feladata marad.
    """
    from app import models

    provider = (
        db.query(models.Provider)
        .filter(models.Provider.user_id == current_user.id)
        .first()
    )
    if provider:
        return provider

    memberships = getattr(current_user, "clinic_memberships", None) or []
    active_memberships = [
        membership
        for membership in memberships
        if getattr(membership, "is_active", False)
    ]

    if not active_memberships:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="No clinic membership found",
        )

    clinic_ids = []
    for membership in active_memberships:
        clinic_id = getattr(membership, "clinic_id", None)
        if clinic_id is not None and clinic_id not in clinic_ids:
            clinic_ids.append(clinic_id)

    if not clinic_ids:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="No clinic membership found",
        )

    provider = (
        db.query(models.Provider)
        .filter(
            models.Provider.clinic_id.in_(clinic_ids),
            models.Provider.is_active == True,  # noqa: E712
        )
        .order_by(models.Provider.id.asc())
        .first()
    )

    if not provider:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No provider found for this clinic",
        )

    return provider