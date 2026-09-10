"""BYOK: 新增 user_api_keys 表

Revision ID: 0002
Revises: 0001
Create Date: 2026-09-02

说明:
    为 BYOK(用户自带密钥)功能建 user_api_keys 表。
    结构见 ryoshi.db.models.UserApiKey。
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0002"
down_revision: str | Sequence[str] | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """建 user_api_keys 表。幂等:已存在则跳过(0001 用 create_all 会带出新模型)。"""

    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "user_api_keys" in inspector.get_table_names():
        return

    op.create_table(
        "user_api_keys",
        sa.Column("id", sa.String(length=191), primary_key=True),
        sa.Column("user_id", sa.String(length=255), nullable=False),
        sa.Column("provider", sa.String(length=256), nullable=False),
        sa.Column("encrypted_api_key", sa.Text(), nullable=False),
        sa.Column("base_url", sa.Text(), nullable=True),
        sa.Column("models", sa.Text(), nullable=True),
        sa.Column("provider_name", sa.String(length=256), nullable=True),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now()),
        sa.UniqueConstraint("user_id", "provider", name="user_api_keys_user_provider_uniq"),
    )
    op.create_index("user_api_keys_user_id_idx", "user_api_keys", ["user_id"])


def downgrade() -> None:
    op.drop_index("user_api_keys_user_id_idx", table_name="user_api_keys")
    op.drop_table("user_api_keys")
