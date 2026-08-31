"""Ryoshi 后端服务入口。

设计意图:
    这是 FastAPI 应用的装配点,只做三件事:
      1. 创建 app 实例并挂上跨域(CORS)中间件——前端跑在 :3000,后端在 :8000,必须放行
      2. 注册各业务路由(聊天、历史、上传、反馈、分享)
      3. 暴露 /health 健康检查,供 Docker 探活与本地冒烟测试

    业务逻辑一概不写在这里,全部下沉到 api/ 与各业务模块,
    保持这个入口"一眼能看完"。
"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from ryoshi.api.chat import router as chat_router
from ryoshi.api.chats import router as chats_router
from ryoshi.config import get_settings


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """应用生命周期钩子。

    启动时做一次性初始化(建连接池、预热配置),关闭时优雅释放。
    对应原项目在 Next.js instrumentation.ts 里做的启动初始化。
    """
    settings = get_settings()
    # 启动日志:让开发者第一眼确认关键开关状态(不打印密钥本身)
    print(f"[ryoshi] 环境={settings.environment} 认证={'开' if settings.enable_auth else '关(匿名)'}")
    # 初始化数据库连接池(Neon / 本地 Postgres)
    from ryoshi.db.engine import dispose_db, init_db

    init_db()
    yield
    # 关闭阶段:释放数据库连接池
    await dispose_db()


def create_app() -> FastAPI:
    """应用工厂。显式工厂函数便于测试时构造隔离的 app 实例。"""
    app = FastAPI(
        title="Ryoshi",
        description="AI 驱动的生成式 UI 搜索引擎 —— Python 后端",
        version="0.1.0",
        lifespan=lifespan,
    )

    # CORS:开发期前端在 localhost:3000,后端在 :8000。
    # 允许携带 cookie(模型选择、searchMode 都靠 cookie 记忆)。
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:3000", "http://127.0.0.1:3000"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # 业务路由
    app.include_router(chat_router)
    app.include_router(chats_router)

    @app.get("/health", tags=["meta"])
    async def health() -> dict[str, str]:
        """健康检查。返回固定串即可,供 docker-compose 的 healthcheck 与冒烟测试用。"""
        return {"status": "ok", "service": "ryoshi"}

    return app


# uvicorn 启动入口:`uvicorn ryoshi.main:app --reload`
app = create_app()
