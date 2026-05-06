# Path: backend/app/models/patient.py

from sqlalchemy import Column, Date, DateTime, ForeignKey, Integer, String, func
from sqlalchemy.orm import relationship

from app.db import Base


class Patient(Base):
    __tablename__ = "patients"

    id = Column(Integer, primary_key=True, index=True)
    fhir_id = Column(String, nullable=True, unique=True, index=True)

    user_id = Column(
        Integer,
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    first_name = Column(String, nullable=False)
    last_name = Column(String, nullable=False)
    birth_date = Column(Date, nullable=True)
    gender = Column(String, nullable=True)

    phone = Column(String, nullable=True)
    email = Column(String, nullable=True)
    address_line = Column(String, nullable=True)
    city = Column(String, nullable=True)
    county = Column(String, nullable=True)
    postal_code = Column(String, nullable=True)
    country = Column(String, nullable=True, default="RO")

    created_at = Column(DateTime(timezone=True), server_default=func.now())

    user = relationship("User", back_populates="patient_profile")