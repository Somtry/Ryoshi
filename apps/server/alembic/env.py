"""Alembic 迁移环境配置。

设计意图:
    数据库连接串不写死在 alembic.ini 里(那样密钥会进版本库),
    而是从应用的配置中心 get_settings() 读取——与应用运行时保持同源,
    改一处(环境变量 / .env)即可同时影响运行时与迁移。

    在线模式通过 asyncpg 异步驱动执行迁移。
"""

import asyncio
from logging.config import fileConfig

from alembic import context
from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config

# 导入模型元数据,让 Alembic 能自动比对出表结构变更(autogenerate 的基础)
from ryoshi.config import get_settings
from ryoshi.db.engine import normalize_database_url
from ryoshi.db.models import Base

config = context.config

# 把应用的数据库 URL 注入 Alembic 配置(覆盖 ini 里的占位)。
# 复用运行时的规范化逻辑:补 +asyncpg 驱动、翻译 sslmode 等 libpq 参数。
_db_url, _db_connect_args = normalize_database_url(get_settings().database_url)
config.set_main_option("sqlalchemy.url", _db_url)

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# autogenerate 要比对的"目标元数据"
target_metadata = Base.metadata


def run_migrations_offline() -> None:
    """离线模式:只生成 SQL 脚本,不真正连数据库。"""
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection) -> None:
    context.configure(connection=connection, target_metadata=target_metadata)
    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    """在线模式:用异步引擎连库并执行迁移。"""
    connectable = async_engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
        # ssl 等驱动级参数直接以 connect_args 传入(config 无法表达嵌套 dict)
        connect_args=_db_connect_args,
    )
    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)
    await connectable.dispose()


def run_migrations_online() -> None:
    asyncio.run(run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
