"""add clinics memberships and appointment audit fields

Revision ID: f5e97ff93af0
Revises: d61707949f9d
Create Date: 2026-03-12

"""

from alembic import op
import sqlalchemy as sa

revision = "f5e97ff93af0"
down_revision = "d61707949f9d"
branch_labels = None
depends_on = None


def upgrade():

    # ---- clinics table ----
    op.create_table(
        "clinics",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("slug", sa.String(), nullable=True),
        sa.Column("phone", sa.String(), nullable=True),
        sa.Column("email", sa.String(), nullable=True),
        sa.Column("address_line", sa.String(), nullable=True),
        sa.Column("city", sa.String(), nullable=True),
        sa.Column("county", sa.String(), nullable=True),
        sa.Column("postal_code", sa.String(), nullable=True),
        sa.Column("country", sa.String(), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
    )

    op.create_index("ix_clinics_slug", "clinics", ["slug"], unique=True)
    op.create_index("ix_clinics_name", "clinics", ["name"])


    # ---- clinic memberships ----
    op.create_table(
        "clinic_memberships",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("clinic_id", sa.Integer(), nullable=False),
        sa.Column("role", sa.String(), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["clinic_id"], ["clinics.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("user_id", "clinic_id", name="uq_user_clinic_membership"),
    )

    op.create_index("ix_clinic_memberships_user_id", "clinic_memberships", ["user_id"])
    op.create_index("ix_clinic_memberships_clinic_id", "clinic_memberships", ["clinic_id"])


    # ---- providers -> clinic ----
    op.add_column("providers", sa.Column("clinic_id", sa.Integer(), nullable=True))

    op.create_foreign_key(
        "fk_providers_clinic",
        "providers",
        "clinics",
        ["clinic_id"],
        ["id"],
        ondelete="SET NULL",
    )

    op.create_index("ix_providers_clinic_id", "providers", ["clinic_id"])


    # ---- appointments audit fields ----
    op.add_column("appointments", sa.Column("clinic_id", sa.Integer(), nullable=True))
    op.add_column("appointments", sa.Column("created_by_user_id", sa.Integer(), nullable=True))

    op.create_foreign_key(
        "fk_appointments_clinic",
        "appointments",
        "clinics",
        ["clinic_id"],
        ["id"],
        ondelete="SET NULL",
    )

    op.create_foreign_key(
        "fk_appointments_created_by",
        "appointments",
        "users",
        ["created_by_user_id"],
        ["id"],
        ondelete="SET NULL",
    )

    op.create_index("ix_appointments_clinic_id", "appointments", ["clinic_id"])
    op.create_index("ix_appointments_created_by_user_id", "appointments", ["created_by_user_id"])


def downgrade():

    op.drop_index("ix_appointments_created_by_user_id", table_name="appointments")
    op.drop_index("ix_appointments_clinic_id", table_name="appointments")

    op.drop_constraint("fk_appointments_created_by", "appointments", type_="foreignkey")
    op.drop_constraint("fk_appointments_clinic", "appointments", type_="foreignkey")

    op.drop_column("appointments", "created_by_user_id")
    op.drop_column("appointments", "clinic_id")


    op.drop_index("ix_providers_clinic_id", table_name="providers")
    op.drop_constraint("fk_providers_clinic", "providers", type_="foreignkey")
    op.drop_column("providers", "clinic_id")


    op.drop_index("ix_clinic_memberships_clinic_id", table_name="clinic_memberships")
    op.drop_index("ix_clinic_memberships_user_id", table_name="clinic_memberships")
    op.drop_table("clinic_memberships")


    op.drop_index("ix_clinics_name", table_name="clinics")
    op.drop_index("ix_clinics_slug", table_name="clinics")
    op.drop_table("clinics")