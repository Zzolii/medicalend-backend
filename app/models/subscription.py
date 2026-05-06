# Path: backend/app/models/subscription.py

from sqlalchemy import Column, Integer, String, Boolean, DateTime, ForeignKey
from sqlalchemy.sql import func

from app.db import Base


class SubscriptionPlan(Base):
    __tablename__ = "subscription_plans"

    id = Column(Integer, primary_key=True, index=True)

    code = Column(String, unique=True, nullable=False)
    name = Column(String, nullable=False)

    price_eur = Column(Integer, nullable=False, default=0)
    duration_days = Column(Integer, nullable=False)

    is_active = Column(Boolean, default=True)


class ClinicSubscription(Base):
    __tablename__ = "clinic_subscriptions"

    id = Column(Integer, primary_key=True, index=True)

    clinic_id = Column(Integer, nullable=False)
    plan_id = Column(Integer, ForeignKey("subscription_plans.id"), nullable=False)

    status = Column(String, nullable=False)  # trialing / active / expired / canceled

    starts_at = Column(DateTime, nullable=False)
    ends_at = Column(DateTime, nullable=False)

    created_at = Column(DateTime(timezone=True), server_default=func.now())