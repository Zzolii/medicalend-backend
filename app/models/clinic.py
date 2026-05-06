# Path: backend/app/models/clinic.py

from sqlalchemy import Boolean, Column, DateTime, Integer, String, func
from sqlalchemy.orm import relationship

from app.db import Base


class Clinic(Base):
    __tablename__ = "clinics"

    id = Column(Integer, primary_key=True, index=True)

    name = Column(String, nullable=False, index=True)
    slug = Column(String, nullable=True, unique=True, index=True)

    phone = Column(String, nullable=True)
    email = Column(String, nullable=True)

    address_line = Column(String, nullable=True)
    city = Column(String, nullable=True)
    county = Column(String, nullable=True)
    postal_code = Column(String, nullable=True)
    country = Column(String, nullable=True, default="RO")

    is_active = Column(Boolean, nullable=False, default=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now())

    memberships = relationship(
        "ClinicMembership",
        back_populates="clinic",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )

    providers = relationship(
        "Provider",
        back_populates="clinic",
    )

    appointments = relationship(
        "Appointment",
        back_populates="clinic",
    )