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


class ProviderSpecialty(Base):
    __tablename__ = "provider_specialties"
    __table_args__ = (
        UniqueConstraint("provider_id", "name", name="uq_provider_specialty_name"),
    )

    id = Column(Integer, primary_key=True, index=True)
    provider_id = Column(
        Integer,
        ForeignKey("providers.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    name = Column(String, nullable=False, index=True)
    is_active = Column(Boolean, nullable=False, default=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now())

    provider = relationship("Provider", back_populates="specialties")
    doctors = relationship(
        "ProviderDoctor",
        back_populates="specialty",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )