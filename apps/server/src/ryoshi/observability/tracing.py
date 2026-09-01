"""Langfuse 链路追踪(对应原项目 instrumentation.ts + lib/utils/telemetry.ts)。

设计意图:
    原项目用 @langfuse/tracing 的 startActiveObservation 包住整个研究流,
    让 researcher agent 和 title-generation span 共享一个 trace。
    Ryoshi 用 langfuse Python SDK v4 做同样的事:
      - 一个 trace 对应一次 /api/chat 请求
      - trace 内嵌 span:模型调用(quick/adaptive researcher)、工具调用(search/fetch)
      - traceId 写入消息 metadata,前端反馈按钮据此关联评分

    未配置密钥时全部为空操作(no-op),不影响主流程。
"""

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from ryoshi.config import get_settings

logger = logging.getLogger("ryoshi.tracing")

# 全局单例,惰性初始化
_client: Any = None
_initialized = False


def is_tracing_enabled() -> bool:
    """是否开启了链路追踪。两个 key 都配了才启用。"""
    return get_settings().is_tracing_enabled


def langfuse_client() -> Any:
    """获取 Langfuse 客户端单例。未配置时返回 None(所有操作空转)。"""
    global _client, _initialized
    if _initialized:
        return _client

    _initialized = True
    s = get_settings()
    if not s.is_tracing_enabled:
        logger.info("Langfuse 未配置(LANGFUSE_PUBLIC_KEY/SECRET_KEY),追踪关闭")
        _client = None
        return None

    try:
        from langfuse import Langfuse

        _client = Langfuse(
            public_key=s.langfuse_public_key,
            secret_key=s.langfuse_secret_key,
            host=s.langfuse_host,
        )
        logger.info("Langfuse 追踪已启用 → %s", s.langfuse_host)
        return _client
    except Exception:
        logger.exception("Langfuse 初始化失败,追踪降级为关闭")
        _client = None
        return None


@asynccontextmanager
async def research_trace(
    chat_id: str,
    user_id: str,
    model_id: str,
    search_mode: str,
) -> AsyncIterator[str | None]:
    """为一次研究请求创建 Langfuse trace。

    对应原项目 propagateAttributes + startActiveObservation('research', ...)。
    产出 trace_id(写入消息 metadata,供前端反馈关联)。

    未启用追踪时 yield None,调用方不感知差异。
    """
    client = langfuse_client()
    if client is None:
        yield None
        return

    try:
        with client.start_as_current_observation(
            name="research",
            as_type="span",
            metadata={
                "chatId": chat_id,
                "userId": user_id,
                "modelId": model_id,
                "searchMode": search_mode,
            },
            end_on_exit=True,
        ) as span:
            yield span.trace_id
    except Exception:
        logger.exception("Langfuse trace 创建失败,不影响主流程")
        yield None


async def flush_traces() -> None:
    """冲刷缓冲的追踪数据。应用关闭时调用。"""
    if _client is not None:
        try:
            _client.flush()
        except Exception:
            logger.exception("Langfuse flush 失败")
