"""Ryoshi 后端服务入口。

设计意图:
    这是 FastAPI 应用的装配点,只做三件事:
      1. 创建 app 实例并挂上跨域(CORS)中间件——前端跑在 :3000,后端在 :8000,必须放行
      2. 注册各业务路由(聊天、历史、上传、反馈、分享)
      3. 暴露 /health 健康检查,供 Docker 探活与本地冒烟测试

    业务逻辑一概不写在这里,全部下沉到 api/ 与各业务模块,
    保持这个入口"一眼能看完"。
"""

import logging
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware

from ryoshi.api.chat import router as chat_router
from ryoshi.api.chats import router as chats_router
from ryoshi.api.feedback import router as feedback_router
from ryoshi.api.files import router as files_router
from ryoshi.api.keys import router as keys_router
from ryoshi.api.models import router as models_router
from ryoshi.api.notes import router as notes_router
from ryoshi.api.relay import router as relay_router
from ryoshi.api.upload import router as upload_router
from ryoshi.config import get_settings

logger = logging.getLogger("ryoshi")


def _configure_ryoshi_logger() -> None:
    """把 ryoshi.* logger 挂上 uvicorn 同款输出。

    uvicorn 的默认 LOGGING_CONFIG 只配置 uvicorn.* 三个 logger;
    其他 logger 传播到 root 后无 handler,INFO 会被 Python 的
    lastResort(WARNING 级)吞掉。这里给 ryoshi 加 StreamHandler,
    与 uvicorn 输出同去 stdout,格式对齐;重复调用幂等(dev reload)。
    """
    if logger.handlers:  # reload 场景已配置
        return
    handler = logging.StreamHandler()
    handler.setFormatter(
        logging.Formatter("%(levelname)s:     %(name)s - %(message)s")
    )
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    # 不向 root 传播(避免双写)
    logger.propagate = False


_configure_ryoshi_logger()


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """应用生命周期钩子。

    启动时做一次性初始化(建连接池、预热配置),关闭时优雅释放。
    对应原项目在 Next.js instrumentation.ts 里做的启动初始化。
    """
    settings = get_settings()
    # 启动日志:让开发者第一眼确认关键开关状态(不打印密钥本身)
    logger.info(
        "环境=%s 认证=%s workers=%s",
        settings.environment,
        "开" if settings.enable_auth else "关(匿名)",
        "多进程(见启动参数)" if settings.environment != "development" else "单进程(dev)",
    )
    # 初始化数据库连接池(Neon / 本地 Postgres)
    from ryoshi.db.engine import dispose_db, init_db

    init_db()
    # 共享 httpx 客户端(搜索/抓取/JWKS/relay 的进程级连接池)
    from ryoshi.http import close_http_client, init_http_client

    init_http_client()
    yield
    # 关闭阶段:释放数据库连接池与 HTTP 连接池
    await close_http_client()
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
    # 来源清单可配置(ALLOWED_ORIGINS,逗号分隔)——部署到任意域名时
    # 改环境变量即可,不用动代码;生产同域(nginx 反代 /api)时跨域
    # 请求根本不会发生,清单留默认也无害。
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[
            o.strip()
            for o in get_settings().allowed_origins.split(",")
            if o.strip()
        ],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # 业务路由
    app.include_router(chat_router)
    app.include_router(chats_router)
    app.include_router(models_router)
    app.include_router(upload_router)
    app.include_router(notes_router)
    app.include_router(feedback_router)
    app.include_router(files_router)
    app.include_router(keys_router)
    # PostHog 反代(前端 /relay → PostHog US cloud,对应原项目 rewrites)
    app.include_router(relay_router)

    # 请求访问日志:方法/路径/状态/耗时(排障刚需;跳过 /health 探活刷屏)。
    # 用中间件而非 uvicorn access-log:格式统一进 ryoshi logger,且能带耗时。
    @app.middleware("http")
    async def access_log(request: Request, call_next):
        if request.url.path == "/health":
            return await call_next(request)
        start = time.perf_counter()
        response = await call_next(request)
        elapsed_ms = (time.perf_counter() - start) * 1000
        # SSE 流式响应的"耗时"是首字节时间(响应头返回即计时结束),
        # 真实流时长看业务日志,这里标注 stream 提示阅读者。
        logger.info(
            "%s %s -> %s (%.1fms%s)",
            request.method,
            request.url.path,
            response.status_code,
            elapsed_ms,
            ", stream" if response.headers.get("content-type", "").startswith("text/event-stream") else "",
        )
        return response

    @app.get("/health", tags=["meta"])
    async def health() -> dict[str, str]:
        """健康检查。返回固定串即可,供 docker-compose 的 healthcheck 与冒烟测试用。"""
        return {"status": "ok", "service": "ryoshi"}

    return app


# uvicorn 启动入口:`uvicorn ryoshi.main:app --reload`
app = create_app()
