"""tenant Entra (Azure AD) directory connection columns

Adds the per-tenant Microsoft Entra ID connection used by the directory sync:
entra_tenant_id, entra_client_id, entra_client_secret (write-only). All
nullable and additive, so the upgrade is safe on an existing database; NULL
falls back to the server ENTRA_* env values.

Revision ID: d4e5f6a7b8c9
Revises: c3d4e5f6a7b8
Create Date: 2026-08-26

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'd4e5f6a7b8c9'
down_revision: Union[str, Sequence[str], None] = 'c3d4e5f6a7b8'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _existing_columns() -> set[str]:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    return {c["name"] for c in insp.get_columns("tenants")}


def upgrade() -> None:
    have = _existing_columns()
    to_add = [
        ("entra_tenant_id", sa.Column("entra_tenant_id", sa.String(length=100), nullable=True)),
        ("entra_client_id", sa.Column("entra_client_id", sa.String(length=100), nullable=True)),
        ("entra_client_secret", sa.Column("entra_client_secret", sa.String(length=256), nullable=True)),
    ]
    with op.batch_alter_table("tenants", schema=None) as batch_op:
        for name, col in to_add:
            if name not in have:
                batch_op.add_column(col)


def downgrade() -> None:
    have = _existing_columns()
    with op.batch_alter_table("tenants", schema=None) as batch_op:
        for name in ("entra_client_secret", "entra_client_id", "entra_tenant_id"):
            if name in have:
                batch_op.drop_column(name)
