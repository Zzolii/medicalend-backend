# Path: backend/app/models/appointment.py

from sqlalchemy import Column, DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import relationship

from app.db import Base


class Appointment(Base):
    __tablename__ = "appointments"

    id = Column(Integer, primary_key=True, index=True)
    fhir_id = Column(String, nullable=True, unique=True, index=True)

    patient_id = Column(Integer, ForeignKey("patients.id"), nullable=False, index=True)
    provider_id = Column(Integer, ForeignKey("providers.id"), nullable=False, index=True)

    doctor_id = Column(
        Integer,
        ForeignKey("provider_doctors.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    episode_id = Column(
        Integer,
        ForeignKey("care_episodes.id"),
        nullable=True,
        index=True,
    )

    clinic_id = Column(
        Integer,
        ForeignKey("clinics.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    created_by_user_id = Column(
        Integer,
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    google_calendar_integration_id = Column(
        Integer,
        ForeignKey("google_calendar_integrations.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    google_event_id = Column(String, nullable=True, index=True)
    google_sync_status = Column(String, nullable=False, default="not_synced")
    google_sync_error = Column(Text, nullable=True)

    start_time = Column(DateTime(timezone=True), nullable=False)
    end_time = Column(DateTime(timezone=True), nullable=True)

    status = Column(String, nullable=False, default="scheduled")
    notes = Column(String, nullable=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now())

    patient = relationship("Patient", backref="appointments")
    provider = relationship("Provider", backref="appointments")
    doctor = relationship("ProviderDoctor", backref="appointments")
    episode = relationship("CareEpisode", backref="appointments")

    clinic = relationship("Clinic", back_populates="appointments")

    google_calendar_integration = relationship("GoogleCalendarIntegration")

    created_by_user = relationship(
        "User",
        back_populates="created_appointments",
        foreign_keys=[created_by_user_id],
    )