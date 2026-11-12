"""tenant integration + scoring settings columns

Brings the `tenants` table up to the current model: the self-service
integration credentials (webhook_secret, ingest_token) and the per-tenant
scoring override (hrs_aggregation, hrs_blend_alpha). All nullable, so the
upgrade is additive and safe on an existing database. NULL scoring columns
inherit the server default; NULL secret columns fall back to env config.

Revision ID: a1b2c3d4e5f6
Revises: e75427bae515
Create Date: 2026-08-20

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'a1b2c3d4e5f6'
down_revision: Union[str, Sequence[str], None] = 'e75427bae515'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _existing_columns() -> set[str]:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    return {c["name"] for c in insp.get_columns("tenants")}


def upgrade() -> None:
    """Upgrade schema (idempotent per column so it tolerates a DB that was
    created via create_all with some columns already present)."""
    have = _existing_columns()
    to_add = [
        ("webhook_secret", sa.Column("webhook_secret", sa.String(length=64), nullable=True)),
        ("ingest_token", sa.Column("ingest_token", sa.String(length=64), nullable=True)),
        ("hrs_aggregation", sa.Column("hrs_aggregation", sa.String(length=16), nullable=True)),
        ("hrs_blend_alpha", sa.Column("hrs_blend_alpha", sa.Float(), nullable=True)),
    ]
    with op.batch_alter_table("tenants", schema=None) as batch_op:
        for name, col in to_add:
            if name not in have:
                batch_op.add_column(col)


def downgrade() -> None:
    """Downgrade schema."""
    have = _existing_columns()
    with op.batch_alter_table("tenants", schema=None) as batch_op:
        for name in ("hrs_blend_alpha", "hrs_aggregation", "ingest_token", "webhook_secret"):
            if name in have:
                batch_op.drop_column(name)
