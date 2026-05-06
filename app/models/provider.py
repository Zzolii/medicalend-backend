# Path: backend/app/models/provider.py

from sqlalchemy import Boolean, Column, Date, DateTime, ForeignKey, Integer, String, func
from sqlalchemy.orm import relationship

from app.db import Base


class Provider(Base):
    __tablename__ = "providers"

    id = Column(Integer, primary_key=True, index=True)

    user_id = Column(
        Integer,
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        unique=True,
        index=True,
    )

    clinic_id = Column(
        Integer,
        ForeignKey("clinics.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    fhir_id = Column(String, nullable=True, unique=True, index=True)

    name = Column(String, nullable=False)
    provider_type = Column(String, nullable=False, default="clinic", index=True)

    website = Column(String, nullable=True)
    image_url = Column(String, nullable=True)
    public_description = Column(String, nullable=True)

    specialty = Column(String, nullable=True)
    services_offered = Column(String, nullable=True)

    license_number = Column(String, nullable=True, unique=True)

    cui = Column(String, nullable=True, unique=True, index=True)
    trade_register_number = Column(String, nullable=True, unique=True, index=True)

    contact_person_name = Column(String, nullable=True)
    contact_email = Column(String, nullable=True)
    contact_phone = Column(String, nullable=True)

    phone = Column(String, nullable=True)
    email = Column(String, nullable=True)

    address_line = Column(String, nullable=True)
    city = Column(String, nullable=True, index=True)
    county = Column(String, nullable=True, index=True)
    postal_code = Column(String, nullable=True)
    country = Column(String, nullable=True, default="RO")

    coverage_area = Column(String, nullable=True)

    sanitary_authorization_number = Column(String, nullable=True)
    sanitary_authorization_expires_at = Column(Date, nullable=True)

    healthcare_compliance_confirmed = Column(Boolean, nullable=False, default=False)
    provider_agreement_accepted = Column(Boolean, nullable=False, default=False)

    is_active = Column(Boolean, default=True)

    status = Column(String, nullable=False, default="pending", index=True)
    rejection_reason = Column(String, nullable=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now())

    user = relationship("User", back_populates="provider_profile", uselist=False)

    clinic = relationship("Clinic", back_populates="providers")

    specialties = relationship(
        "ProviderSpecialty",
        back_populates="provider",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )

    doctors = relationship(
        "ProviderDoctor",
        back_populates="provider",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )