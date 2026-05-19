# Path: backend/alembic/versions/a36ad2878dbc_add_appointment_reminder_email_sent_at.py

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "a36ad2878dbc"
down_revision: Union[str, None] = "57fc521858c7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "appointments",
        sa.Column(
            "reminder_email_sent_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
    )


def downgrade() -> None:
    op.drop_column("appointments", "reminder_email_sent_at")