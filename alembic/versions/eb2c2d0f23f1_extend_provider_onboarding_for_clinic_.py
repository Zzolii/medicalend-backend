# Path: backend/alembic/versions/eb2c2d0f23f1_extend_provider_onboarding_for_clinic_and_home_care.py

"""extend provider onboarding for clinic and home care

Revision ID: eb2c2d0f23f1
Revises: f5e97ff93af0
Create Date: 2026-03-12 12:02:38.881331

"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "eb2c2d0f23f1"
down_revision = "f5e97ff93af0"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "providers",
        sa.Column(
            "provider_type",
            sa.String(),
            nullable=False,
            server_default="clinic",
        ),
    )
    op.add_column("providers", sa.Column("services_offered", sa.String(), nullable=True))
    op.add_column("providers", sa.Column("cui", sa.String(), nullable=True))
    op.add_column("providers", sa.Column("trade_register_number", sa.String(), nullable=True))
    op.add_column("providers", sa.Column("contact_person_name", sa.String(), nullable=True))
    op.add_column("providers", sa.Column("contact_email", sa.String(), nullable=True))
    op.add_column("providers", sa.Column("contact_phone", sa.String(), nullable=True))
    op.add_column("providers", sa.Column("coverage_area", sa.String(), nullable=True))
    op.add_column("providers", sa.Column("sanitary_authorization_number", sa.String(), nullable=True))
    op.add_column("providers", sa.Column("sanitary_authorization_expires_at", sa.Date(), nullable=True))
    op.add_column(
        "providers",
        sa.Column(
            "healthcare_compliance_confirmed",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )
    op.add_column(
        "providers",
        sa.Column(
            "provider_agreement_accepted",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )

    op.create_index(op.f("ix_providers_provider_type"), "providers", ["provider_type"], unique=False)
    op.create_index(op.f("ix_providers_cui"), "providers", ["cui"], unique=True)
    op.create_index(
        op.f("ix_providers_trade_register_number"),
        "providers",
        ["trade_register_number"],
        unique=True,
    )

    # levesszük a server defaultot, hogy később már az app töltse ki explicit
    op.alter_column("providers", "provider_type", server_default=None)
    op.alter_column("providers", "healthcare_compliance_confirmed", server_default=None)
    op.alter_column("providers", "provider_agreement_accepted", server_default=None)


def downgrade() -> None:
    op.drop_index(op.f("ix_providers_trade_register_number"), table_name="providers")
    op.drop_index(op.f("ix_providers_cui"), table_name="providers")
    op.drop_index(op.f("ix_providers_provider_type"), table_name="providers")

    op.drop_column("providers", "provider_agreement_accepted")
    op.drop_column("providers", "healthcare_compliance_confirmed")
    op.drop_column("providers", "sanitary_authorization_expires_at")
    op.drop_column("providers", "sanitary_authorization_number")
    op.drop_column("providers", "coverage_area")
    op.drop_column("providers", "contact_phone")
    op.drop_column("providers", "contact_email")
    op.drop_column("providers", "contact_person_name")
    op.drop_column("providers", "trade_register_number")
    op.drop_column("providers", "cui")
    op.drop_column("providers", "services_offered")
    op.drop_column("providers", "provider_type")