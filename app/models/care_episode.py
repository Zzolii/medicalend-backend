# Path: backend/app/models/care_episode.py

from sqlalchemy import Column, Integer, String, DateTime, ForeignKey, func
from sqlalchemy.orm import relationship

from app.db import Base


class CareEpisode(Base):
    __tablename__ = "care_episodes"

    id = Column(Integer, primary_key=True, index=True)

    patient_id = Column(Integer, ForeignKey("patients.id"), nullable=False)
    owner_provider_id = Column(Integer, ForeignKey("providers.id"), nullable=False)

    title = Column(String, nullable=False)  # pl. "Sebkezelés – boka"
    status = Column(String, nullable=False, default="open")  # open / closed

    created_at = Column(DateTime(timezone=True), server_default=func.now())

    # Relations
    patient = relationship("Patient")
    owner_provider = relationship("Provider")

    tasks = relationship("CareTask", back_populates="episode", cascade="all, delete-orphan")
    notes = relationship("CareNote", back_populates="episode", cascade="all, delete-orphan")
