# Path: backend/app/models/clinic_membership.py

from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Integer, String, UniqueConstraint, func
from sqlalchemy.orm import relationship

from app.db import Base


class ClinicMembership(Base):
    __tablename__ = "clinic_memberships"
    __table_args__ = (
        UniqueConstraint("user_id", "clinic_id", name="uq_user_clinic_membership"),
    )

    id = Column(Integer, primary_key=True, index=True)

    user_id = Column(
        Integer,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    clinic_id = Column(
        Integer,
        ForeignKey("clinics.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    role = Column(String, nullable=False, default="clinic_admin", index=True)

    # Optional doctor linkage:
    # - doctor role esetén használjuk
    # - assistant / reception / clinic_admin esetén NULL
    provider_doctor_id = Column(
        Integer,
        ForeignKey("provider_doctors.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    is_active = Column(Boolean, nullable=False, default=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now())

    user = relationship("User", back_populates="clinic_memberships")
    clinic = relationship("Clinic", back_populates="memberships")
    provider_doctor = relationship("ProviderDoctor")