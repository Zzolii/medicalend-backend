# Path: backend/app/models/medical_document.py

from sqlalchemy import Column, DateTime, ForeignKey, Integer, String, func
from sqlalchemy.orm import relationship

from app.db import Base


class MedicalDocument(Base):
    __tablename__ = "medical_documents"

    id = Column(Integer, primary_key=True, index=True)

    episode_id = Column(
        Integer,
        ForeignKey("care_episodes.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    appointment_id = Column(
        Integer,
        ForeignKey("appointments.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    uploaded_by_user_id = Column(
        Integer,
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    file_name = Column(String, nullable=False)
    stored_name = Column(String, nullable=False, unique=True, index=True)
    file_url = Column(String, nullable=False)
    mime_type = Column(String, nullable=False, default="application/pdf")

    created_at = Column(DateTime(timezone=True), server_default=func.now())

    episode = relationship("CareEpisode", backref="documents")
    appointment = relationship("Appointment", backref="documents")
    uploaded_by_user = relationship("User")