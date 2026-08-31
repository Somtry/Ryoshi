"""初始建表: chats / messages / parts / notes / files / feedback

Revision ID: 0001
Revises:
Create Date: 2026-08-31

说明:
    首个迁移,建立与原 morhpic 项目兼容的全部六张表。
    直接基于模型元数据 create_all,保证与 ryoshi.db.models 严格一致;
    后续表结构变更再用 alembic revision --autogenerate 增量生成。
"""

from collections.abc import Sequence

from alembic import op

# revision 标识,Alembic 用它串起迁移链
revision: str = "0001"
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """建表。从模型元数据创建全部表、索引与约束。"""
    from ryoshi.db.models import Base

    bind = op.get_bind()
    Base.metadata.create_all(bind=bind)


def downgrade() -> None:
    """回滚:按外键依赖的逆序删除全部表。"""
    from ryoshi.db.models import Base

    bind = op.get_bind()
    Base.metadata.drop_all(bind=bind)
