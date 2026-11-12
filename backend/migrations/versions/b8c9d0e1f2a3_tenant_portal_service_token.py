"""tenant portal service token

Adds tenants.portal_service_token (nullable, encrypted at rest via the
EncryptedSecret column type - stored as TEXT). This is a new, brand-new
secret with nothing to backfill, unlike the a7b8c9d0e1f2 migration - so this
one is a plain additive column, no data rewrite needed.

Revision ID: b8c9d0e1f2a3
Revises: a7b8c9d0e1f2
Create Date: 2026-09-15

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'b8c9d0e1f2a3'
down_revision: Union[str, Sequence[str], None] = 'a7b8c9d0e1f2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _existing_columns() -> set[str]:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    return {c["name"] for c in insp.get_columns("tenants")}


def upgrade() -> None:
    have = _existing_columns()
    with op.batch_alter_table("tenants", schema=None) as batch_op:
        if "portal_service_token" not in have:
            batch_op.add_column(sa.Column("portal_service_token", sa.Text(), nullable=True))


def downgrade() -> None:
    have = _existing_columns()
    with op.batch_alter_table("tenants", schema=None) as batch_op:
        if "portal_service_token" in have:
            batch_op.drop_column("portal_service_token")
