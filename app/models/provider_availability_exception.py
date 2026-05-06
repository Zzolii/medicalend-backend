# Path: backend/app/models/provider_availability_exception.py

from sqlalchemy import Column, Integer, Date, Time, Boolean, String, ForeignKey, UniqueConstraint
from app.db import Base


class ProviderAvailabilityException(Base):
    """
    Exception day:
    - is_closed=True -> no availability
    - else optional start_time/end_time override for that date

    doctor_id:
    - NULL  -> provider-level fallback exception
    - value -> doctor-specific exception
    """
    __tablename__ = "provider_availability_exceptions"
    __table_args__ = (
        UniqueConstraint("provider_id", "doctor_id", "date", name="uq_provider_doctor_exception_date"),
    )

    id = Column(Integer, primary_key=True, index=True)
    provider_id = Column(
        Integer,
        ForeignKey("providers.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    doctor_id = Column(
        Integer,
        ForeignKey("provider_doctors.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )

    date = Column(Date, nullable=False, index=True)
    is_closed = Column(Boolean, nullable=False, default=False)

    start_time = Column(Time, nullable=True)
    end_time = Column(Time, nullable=True)

    note = Column(String, nullable=True)