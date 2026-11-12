"""employee portal signal columns

Adds the per-employee signals written by the separate Awareness & Remediation
Portal over the REST API: risk_floor (a baseline HRS the score is held at-or-
above, e.g. a new hire set to Moderate after onboarding), and the in-person
awareness mark (needs_inperson_awareness / inperson_reason / inperson_since)
raised when a user is stuck High/Critical for too long. All nullable/defaulted
and additive, so the upgrade is safe on an existing database.

Revision ID: c3d4e5f6a7b8
Revises: b2c3d4e5f6a7
Create Date: 2026-08-23

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'c3d4e5f6a7b8'
down_revision: Union[str, Sequence[str], None] = 'b2c3d4e5f6a7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _existing_columns() -> set[str]:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    return {c["name"] for c in insp.get_columns("employees")}


def upgrade() -> None:
    have = _existing_columns()
    to_add = [
        ("risk_floor", sa.Column("risk_floor", sa.Float(), nullable=True)),
        ("needs_inperson_awareness", sa.Column(
            "needs_inperson_awareness", sa.Boolean(),
            nullable=False, server_default=sa.false())),
        ("inperson_reason", sa.Column(
            "inperson_reason", sa.String(length=300), nullable=True)),
        ("inperson_since", sa.Column(
            "inperson_since", sa.DateTime(timezone=True), nullable=True)),
    ]
    with op.batch_alter_table("employees", schema=None) as batch_op:
        for name, col in to_add:
            if name not in have:
                batch_op.add_column(col)


def downgrade() -> None:
    have = _existing_columns()
    with op.batch_alter_table("employees", schema=None) as batch_op:
        for name in ("inperson_since", "inperson_reason",
                     "needs_inperson_awareness", "risk_floor"):
            if name in have:
                batch_op.drop_column(name)
