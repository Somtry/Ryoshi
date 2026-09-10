"""数据库引擎与会话管理。

设计意图:
    SQLAlchemy 2.0 的异步模式把"连接池"和"会话"分开:
      - engine  是全局唯一的连接池,进程启动时建一次,随应用关闭而释放
      - session 是每次请求/任务内的工作单元,用完即关,绝不在请求间共享

    这里用 async_sessionmaker 造一个会话工厂,配合 FastAPI 的依赖注入
    在每个请求里拿到一个独立会话。这样多个请求并发时互不干扰,
    也不会出现"一个会话被多处复用导致的事务串台"。
"""

from collections.abc import AsyncIterator

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from ryoshi.config import get_settings

# 全局引擎与会话工厂,在 init_db 里初始化一次
_engine: AsyncEngine | None = None
_session_factory: async_sessionmaker[AsyncSession] | None = None


def normalize_database_url(url: str) -> str:
    """把用户粘贴的 Postgres 连接串规范化为 SQLAlchemy+asyncpg 可用形式。

    两件事:
      1. "postgresql://..." → "postgresql+asyncpg://..."(显式指定异步驱动)
      2. libpq 风格的 ?sslmode=require&channel_binding=require 翻译成
         asyncpg 的 connect_args 能认的形式(sslmode 只保留到 URL 层,
         真正的 ssl 开关由调用方从返回值里读)

    返回 (url, connect_args) 二元组;connect_args 可直接喂给 create_async_engine。
    该函数同时为运行时(init_db)与 Alembic 迁移(env.py)服务,避免两处
    各写一遍解析逻辑又不同步。
    """
    if url.startswith("postgresql://"):
        url = url.replace("postgresql://", "postgresql+asyncpg://", 1)

    connect_args: dict = {}
    if "?" in url:
        base, query = url.split("?", 1)
        params = dict(p.split("=", 1) for p in query.split("&") if "=" in p)
        sslmode = params.pop("sslmode", None)
        params.pop("channel_binding", None)  # asyncpg 不支持,丢弃
        if sslmode in ("require", "verify-ca", "verify-full"):
            connect_args["ssl"] = True
        elif sslmode == "disable":
            connect_args["ssl"] = False
        url = base + ("?" + "&".join(f"{k}={v}" for k, v in params.items()) if params else "")
    return url, connect_args


def init_db() -> AsyncEngine:
    """创建全局异步引擎(连接池)。

    pool_pre_ping=True 让连接在取用前先探活,避免拿到数据库侧已断开的死连接;
    这对长时间运行的服务很重要(数据库可能因超时主动断开空闲连接)。

    连接串规范:用户常直接粘贴 Neon/Supabase 给的 "postgresql://..." 形式,
    而 SQLAlchemy 异步需要显式指定 asyncpg 驱动("postgresql+asyncpg://...")。
    这里统一规范化,免去手动改连接串。

    SSL 参数:Neon 等给的连接串常带 libpq 风格的 ?sslmode=require&channel_binding=require,
    但 asyncpg 不认这两个 query 参数(会报 "unexpected keyword argument")。
    这里把 sslmode=require 翻译成 asyncpg 的 ssl=True,并剥掉 channel_binding。
    """
    global _engine, _session_factory
    settings = get_settings()
    url, connect_args = normalize_database_url(settings.database_url)

    # 连接池参数仅对支持多连接的方言有意义:SQLite(aiosqlite,含内存库)
    # 走 StaticPool 单连接,不接受 pool_size/max_overflow(测试与脚本场景)。
    pool_kwargs: dict = {}
    if not url.startswith("sqlite"):
        pool_kwargs = {"pool_pre_ping": True, "pool_size": 10, "max_overflow": 20}

    _engine = create_async_engine(
        url,
        echo=False,  # 调试时可改 True 打印 SQL
        connect_args=connect_args,
        **pool_kwargs,
    )
    _session_factory = async_sessionmaker(
        bind=_engine,
        class_=AsyncSession,
        expire_on_commit=False,  # 提交后对象仍可读,避免懒加载触发额外查询
    )
    return _engine


async def dispose_db() -> None:
    """释放连接池。应用关闭时调用(lifespan 的清理阶段)。"""
    global _engine
    if _engine is not None:
        await _engine.dispose()
        _engine = None


def get_session_factory() -> async_sessionmaker[AsyncSession]:
    """取会话工厂。未初始化时先初始化,便于脚本/测试单独使用。"""
    global _session_factory
    if _session_factory is None:
        init_db()
    assert _session_factory is not None
    return _session_factory


async def get_session() -> AsyncIterator[AsyncSession]:
    """FastAPI 依赖:为每个请求提供一个独立会话。

    用法:
        @app.get("/x")
        async def handler(db: AsyncSession = Depends(get_session)):
            ...
    请求结束时自动关闭会话(连接归还池中)。
    """
    factory = get_session_factory()
    async with factory() as session:
        yield session
