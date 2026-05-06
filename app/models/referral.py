# Path: backend/app/models/referral.py

from sqlalchemy import Column, Integer, String, DateTime, ForeignKey, func
from sqlalchemy.orm import relationship

from app.db import Base


class Referral(Base):
    __tablename__ = "referrals"

    id = Column(Integer, primary_key=True, index=True)

    episode_id = Column(Integer, ForeignKey("care_episodes.id"), nullable=False)

    from_provider_id = Column(Integer, ForeignKey("providers.id"), nullable=False)
    to_provider_id = Column(Integer, ForeignKey("providers.id"), nullable=False)

    reason = Column(String, nullable=False)

    # pending / accepted / rejected / completed
    status = Column(String, nullable=False, default="pending")
    rejection_reason = Column(String, nullable=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now())

    episode = relationship("CareEpisode")
    from_provider = relationship("Provider", foreign_keys=[from_provider_id])
    to_provider = relationship("Provider", foreign_keys=[to_provider_id])
