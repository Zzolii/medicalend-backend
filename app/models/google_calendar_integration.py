# Path: backend/app/models/google_calendar_integration.py

from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.orm import relationship

from app.db import Base


class GoogleCalendarIntegration(Base):
    __tablename__ = "google_calendar_integrations"
    __table_args__ = (
        UniqueConstraint(
            "clinic_id",
            "provider_id",
            "doctor_id",
            "google_calendar_id",
            name="uq_google_calendar_mapping",
        ),
    )

    id = Column(Integer, primary_key=True, index=True)

    clinic_id = Column(Integer, ForeignKey("clinics.id", ondelete="CASCADE"), nullable=False, index=True)
    provider_id = Column(Integer, ForeignKey("providers.id", ondelete="CASCADE"), nullable=False, index=True)
    doctor_id = Column(Integer, ForeignKey("provider_doctors.id", ondelete="SET NULL"), nullable=True, index=True)

    google_account_email = Column(String, nullable=True, index=True)
    google_calendar_id = Column(String, nullable=False, index=True)
    google_calendar_name = Column(String, nullable=True)

    access_token = Column(Text, nullable=True)
    refresh_token = Column(Text, nullable=True)
    token_uri = Column(String, nullable=True, default="https://oauth2.googleapis.com/token")
    client_id = Column(String, nullable=True)
    client_secret = Column(Text, nullable=True)
    scopes = Column(Text, nullable=True)

    token_expires_at = Column(DateTime(timezone=True), nullable=True)

    sync_direction = Column(String, nullable=False, default="google_bridge")
    status = Column(String, nullable=False, default="configured")

    is_active = Column(Boolean, nullable=False, default=True)

    last_sync_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    clinic = relationship("Clinic")
    provider = relationship("Provider")
    doctor = relationship("ProviderDoctor")