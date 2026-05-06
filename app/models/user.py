# Path: backend/app/models/user.py

from sqlalchemy import Boolean, Column, DateTime, Integer, String, func
from sqlalchemy.orm import relationship

from app.db import Base


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)

    email = Column(String, unique=True, index=True, nullable=False)
    hashed_password = Column(String, nullable=False)

    # Legacy/global role marad MVP kompatibilitás miatt.
    # Jelenleg: provider / admin / patient
    # A klinikán belüli role a ClinicMembership-ben van.
    role = Column(String, nullable=False, default="provider", index=True)

    is_active = Column(Boolean, nullable=False, default=True)

    is_email_verified = Column(Boolean, nullable=False, default=False)
    email_verified_at = Column(DateTime(timezone=True), nullable=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now())

    provider_profile = relationship(
        "Provider",
        back_populates="user",
        uselist=False,
    )

    patient_profile = relationship(
        "Patient",
        back_populates="user",
        uselist=False,
    )

    clinic_memberships = relationship(
        "ClinicMembership",
        back_populates="user",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )

    created_appointments = relationship(
        "Appointment",
        back_populates="created_by_user",
        foreign_keys="Appointment.created_by_user_id",
    )