"""tenant GoPhish sync connection columns

Adds the per-tenant GoPhish REST API connection used by the single-console
sync service: gophish_base_url and gophish_api_key (write-only). Both nullable
and additive, so the upgrade is safe on an existing database; NULL falls back
to the server GOPHISH_API_URL / GOPHISH_API_KEY env values.

Revision ID: b2c3d4e5f6a7
Revises: a1b2c3d4e5f6
Create Date: 2026-08-22

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'b2c3d4e5f6a7'
down_revision: Union[str, Sequence[str], None] = 'a1b2c3d4e5f6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _existing_columns() -> set[str]:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    return {c["name"] for c in insp.get_columns("tenants")}


def upgrade() -> None:
    have = _existing_columns()
    to_add = [
        ("gophish_base_url", sa.Column("gophish_base_url", sa.String(length=300), nullable=True)),
        ("gophish_api_key", sa.Column("gophish_api_key", sa.String(length=128), nullable=True)),
    ]
    with op.batch_alter_table("tenants", schema=None) as batch_op:
        for name, col in to_add:
            if name not in have:
                batch_op.add_column(col)


def downgrade() -> None:
    have = _existing_columns()
    with op.batch_alter_table("tenants", schema=None) as batch_op:
        for name in ("gophish_api_key", "gophish_base_url"):
            if name in have:
                batch_op.drop_column(name)
