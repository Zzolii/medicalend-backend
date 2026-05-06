from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    ForeignKey,
    Integer,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import relationship

from app.db import Base


class ProviderDoctor(Base):
    __tablename__ = "provider_doctors"
    __table_args__ = (
        UniqueConstraint(
            "provider_id",
            "specialty_id",
            "name",
            name="uq_provider_doctor_name",
        ),
    )

    id = Column(Integer, primary_key=True, index=True)

    provider_id = Column(
        Integer,
        ForeignKey("providers.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    specialty_id = Column(
        Integer,
        ForeignKey("provider_specialties.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    name = Column(String, nullable=False, index=True)
    title = Column(String, nullable=True)  # ex.: Dr., Prof. Dr.
    license_number = Column(String, nullable=True)
    phone = Column(String, nullable=True)
    email = Column(String, nullable=True)

    is_active = Column(Boolean, nullable=False, default=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now())

    provider = relationship("Provider", back_populates="doctors")
    specialty = relationship("ProviderSpecialty", back_populates="doctors")