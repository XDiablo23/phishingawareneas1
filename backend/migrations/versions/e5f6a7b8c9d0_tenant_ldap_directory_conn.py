"""tenant on-prem AD (LDAP) directory connection columns

Adds the per-tenant LDAP connection used by the on-prem Active Directory sync:
ldap_uri, ldap_bind_dn, ldap_bind_password (write-only), ldap_base_dn,
ldap_user_filter. All nullable and additive, so the upgrade is safe on an
existing database; NULL falls back to the server LDAP_* env values.

Revision ID: e5f6a7b8c9d0
Revises: d4e5f6a7b8c9
Create Date: 2026-08-26

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'e5f6a7b8c9d0'
down_revision: Union[str, Sequence[str], None] = 'd4e5f6a7b8c9'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _existing_columns() -> set[str]:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    return {c["name"] for c in insp.get_columns("tenants")}


def upgrade() -> None:
    have = _existing_columns()
    to_add = [
        ("ldap_uri", sa.Column("ldap_uri", sa.String(length=200), nullable=True)),
        ("ldap_bind_dn", sa.Column("ldap_bind_dn", sa.String(length=300), nullable=True)),
        ("ldap_bind_password", sa.Column("ldap_bind_password", sa.String(length=256), nullable=True)),
        ("ldap_base_dn", sa.Column("ldap_base_dn", sa.String(length=300), nullable=True)),
        ("ldap_user_filter", sa.Column("ldap_user_filter", sa.String(length=400), nullable=True)),
    ]
    with op.batch_alter_table("tenants", schema=None) as batch_op:
        for name, col in to_add:
            if name not in have:
                batch_op.add_column(col)


def downgrade() -> None:
    have = _existing_columns()
    with op.batch_alter_table("tenants", schema=None) as batch_op:
        for name in ("ldap_user_filter", "ldap_base_dn", "ldap_bind_password",
                     "ldap_bind_dn", "ldap_uri"):
            if name in have:
                batch_op.drop_column(name)
