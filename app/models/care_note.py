# Path: backend/app/models/care_note.py

from sqlalchemy import Column, Integer, String, DateTime, ForeignKey, func
from sqlalchemy.orm import relationship

from app.db import Base


class CareNote(Base):
    __tablename__ = "care_notes"

    id = Column(Integer, primary_key=True, index=True)

    episode_id = Column(Integer, ForeignKey("care_episodes.id"), nullable=False)
    author_user_id = Column(Integer, ForeignKey("users.id"), nullable=False)

    text = Column(String, nullable=False)

    created_at = Column(DateTime(timezone=True), server_default=func.now())

    episode = relationship("CareEpisode", back_populates="notes")
    author = relationship("User")
