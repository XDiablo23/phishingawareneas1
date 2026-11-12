"""tenant per-tenant GoPhish TLS verification override

Adds tenants.gophish_verify_tls (nullable boolean). NULL means "inherit the
server-wide GOPHISH_VERIFY_TLS default"; an explicit true/false lets one
tenant verify (or skip) TLS on its own GoPhish server independently of every
other tenant sharing this deployment. Additive and nullable, so the upgrade
is safe on an existing database.

Revision ID: f6a7b8c9d0e1
Revises: e5f6a7b8c9d0
Create Date: 2026-09-15

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'f6a7b8c9d0e1'
down_revision: Union[str, Sequence[str], None] = 'e5f6a7b8c9d0'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _existing_columns() -> set[str]:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    return {c["name"] for c in insp.get_columns("tenants")}


def upgrade() -> None:
    have = _existing_columns()
    with op.batch_alter_table("tenants", schema=None) as batch_op:
        if "gophish_verify_tls" not in have:
            batch_op.add_column(
                sa.Column("gophish_verify_tls", sa.Boolean(), nullable=True))


def downgrade() -> None:
    have = _existing_columns()
    with op.batch_alter_table("tenants", schema=None) as batch_op:
        if "gophish_verify_tls" in have:
            batch_op.drop_column("gophish_verify_tls")
