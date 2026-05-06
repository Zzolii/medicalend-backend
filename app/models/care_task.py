# Path: backend/app/models/care_task.py

from sqlalchemy import Column, Integer, String, DateTime, ForeignKey, func
from sqlalchemy.orm import relationship

from app.db import Base


class CareTask(Base):
    __tablename__ = "care_tasks"

    id = Column(Integer, primary_key=True, index=True)

    # ✅ mindig tartozik egy episode-hoz
    episode_id = Column(Integer, ForeignKey("care_episodes.id"), nullable=False, index=True)

    # ✅ NEW: opcionálisan konkrét appointmenthez is tartozhat
    appointment_id = Column(Integer, ForeignKey("appointments.id"), nullable=True, index=True)

    title = Column(String, nullable=False)
    due_at = Column(DateTime(timezone=True), nullable=True)

    # todo / doing / done
    status = Column(String, nullable=False, default="todo")

    # provider / patient (MVP)
    assigned_to_role = Column(String, nullable=False, default="provider")

    created_at = Column(DateTime(timezone=True), server_default=func.now())

    episode = relationship("CareEpisode", back_populates="tasks")
    appointment = relationship("Appointment")