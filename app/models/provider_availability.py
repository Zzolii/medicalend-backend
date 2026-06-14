# Path: backend/app/models/provider_availability.py

from sqlalchemy import Boolean, Column, ForeignKey, Integer, Time, UniqueConstraint

from app.db import Base


class ProviderAvailability(Base):
    """
    Weekly availability:
    weekday: 0=Mon ... 6=Sun

    doctor_id:
    - NULL  -> provider-level fallback availability
    - value -> doctor-specific availability

    slot_duration_minutes:
    - controls generated booking slots
    - allowed business values: 5, 10, 15, 20, 30
    """
    __tablename__ = "provider_availabilities"
    __table_args__ = (
        UniqueConstraint(
            "provider_id",
            "doctor_id",
            "weekday",
            name="uq_provider_doctor_weekday",
        ),
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

    weekday = Column(Integer, nullable=False)
    start_time = Column(Time, nullable=False)
    end_time = Column(Time, nullable=False)

    slot_duration_minutes = Column(Integer, nullable=False, default=30)

    is_active = Column(Boolean, nullable=False, default=True)