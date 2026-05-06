# Path: backend/app/schemas/billing.py

from __future__ import annotations

from pydantic import BaseModel


class CreateCheckoutSessionIn(BaseModel):
    plan_id: int


class CreateCheckoutSessionOut(BaseModel):
    checkout_url: str


class BillingPortalOut(BaseModel):
    url: str