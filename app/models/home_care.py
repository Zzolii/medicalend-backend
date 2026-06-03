# Path: backend/app/models/home_care.py

from sqlalchemy import Column, DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import relationship

from app.db import Base


class HomeCareCase(Base):
    __tablename__ = "home_care_cases"

    id = Column(Integer, primary_key=True, index=True)

    patient_id = Column(Integer, ForeignKey("patients.id"), nullable=False, index=True)
    clinic_id = Column(Integer, ForeignKey("clinics.id", ondelete="SET NULL"), nullable=True, index=True)
    owner_provider_id = Column(Integer, ForeignKey("providers.id", ondelete="SET NULL"), nullable=True, index=True)

    title = Column(String, nullable=False)
    status = Column(String, nullable=False, default="active")

    address_line = Column(String, nullable=True)
    city = Column(String, nullable=True)
    county = Column(String, nullable=True)
    contact_phone = Column(String, nullable=True)

    care_plan = Column(Text, nullable=True)

    created_by_user_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    patient = relationship("Patient")
    clinic = relationship("Clinic")
    owner_provider = relationship("Provider")
    created_by_user = relationship("User")

    visits = relationship(
        "HomeCareVisit",
        back_populates="case",
        cascade="all, delete-orphan",
    )


class HomeCareVisit(Base):
    __tablename__ = "home_care_visits"

    id = Column(Integer, primary_key=True, index=True)

    case_id = Column(Integer, ForeignKey("home_care_cases.id"), nullable=False, index=True)
    patient_id = Column(Integer, ForeignKey("patients.id"), nullable=False, index=True)
    clinic_id = Column(Integer, ForeignKey("clinics.id", ondelete="SET NULL"), nullable=True, index=True)

    scheduled_at = Column(DateTime(timezone=True), nullable=False, index=True)
    completed_at = Column(DateTime(timezone=True), nullable=True)

    assigned_user_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True)
    performed_by_user_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True)

    status = Column(String, nullable=False, default="scheduled")

    blood_pressure = Column(String, nullable=True)
    blood_sugar = Column(String, nullable=True)
    pulse = Column(String, nullable=True)
    temperature = Column(String, nullable=True)
    oxygen_saturation = Column(String, nullable=True)

    note = Column(Text, nullable=True)
    created_by_user_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    case = relationship("HomeCareCase", back_populates="visits")
    patient = relationship("Patient")
    clinic = relationship("Clinic")

    assigned_user = relationship("User", foreign_keys=[assigned_user_id])
    performed_by_user = relationship("User", foreign_keys=[performed_by_user_id])
    created_by_user = relationship("User", foreign_keys=[created_by_user_id])