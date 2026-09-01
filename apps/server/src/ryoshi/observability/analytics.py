"""PostHog 服务端事件(对应原项目 lib/analytics/dispatch.ts + track-chat-event.ts)。

设计意图:
    原项目在 Next.js API 路由里用 posthog-node 异步发送事件,
    事件不阻塞聊天主流程(fire-and-forget + try/catch 静默失败)。
    Ryoshi 用 posthog Python SDK 做同样的事:
      - 仅在 RYOSHI_CLOUD_DEPLOYMENT=true 时发送(云端部署)
      - 原始查询文本不上报,只发送派生的 queryShape(长度桶/有无URL/语言)
      - 事件发送失败不影响聊天

    隐私设计(与原项目一致):
      derive_query_shape 把用户查询转成 {queryLenBucket, hasUrl, lang},
      原文只存在数据库里,不会发送到 PostHog。
"""

import logging
import re
from typing import Any

from ryoshi.config import get_settings

logger = logging.getLogger("ryoshi.analytics")

# 全局单例,惰性初始化
_client: Any = None
_initialized = False


def _is_analytics_enabled() -> bool:
    """是否开启分析。仅云端部署(对应原项目 MORPHIC_CLOUD_DEPLOYMENT=true)。"""
    return get_settings().ryoshi_cloud_deployment


def _get_client() -> Any:
    """获取 PostHog 客户端单例。未配置时返回 None。"""
    global _client, _initialized
    if _initialized:
        return _client

    _initialized = True
    s = get_settings()
    if not _is_analytics_enabled() or not s.posthog_api_key:
        _client = None
        return None

    try:
        from posthog import Posthog

        _client = Posthog(
            project_api_key=s.posthog_api_key,
            host=s.posthog_host,
        )
        return _client
    except Exception:
        logger.exception("PostHog 初始化失败,分析降级为关闭")
        _client = None
        return None


# ---- queryShape 计算(对应原项目 lib/analytics/utils.ts) ----

_URL_PATTERN = re.compile(r"https?://", re.IGNORECASE)
_JAPANESE_PATTERN = re.compile(r"[぀-ヿ㐀-鿿]")
_LATIN_PATTERN = re.compile(r"[a-z]", re.IGNORECASE)


def _len_bucket(length: int) -> str:
    if length <= 20:
        return "0-20"
    if length <= 50:
        return "21-50"
    if length <= 120:
        return "51-120"
    return "120+"


def _detect_lang(text: str) -> str:
    if _LATIN_PATTERN.search(text) and not _JAPANESE_PATTERN.search(text):
        return "en"
    return "other"


def derive_query_shape(text: str) -> dict[str, Any]:
    """从原始查询推导隐私安全的形状。原文不上报。"""
    trimmed = text.strip()
    return {
        "queryLenBucket": _len_bucket(len(trimmed)),
        "hasUrl": bool(_URL_PATTERN.search(trimmed)),
        "lang": _detect_lang(trimmed),
    }


def calculate_conversation_turn(
    user_message_ids: list[str], current_message_id: str | None = None
) -> int:
    """计算对话轮次(1-indexed)。对应原项目 calculateConversationTurnFromIds。"""
    ids = set(user_message_ids)
    if current_message_id:
        ids.add(current_message_id)
    return max(1, len(ids))


# ---- 事件发送 ----


def track_chat_event(
    *,
    search_mode: str,
    conversation_turn: int,
    is_new_chat: bool,
    trigger: str,
    chat_id: str,
    distinct_id: str,
    is_guest: bool,
    user_id: str | None = None,
    provider_id: str,
    model_id: str,
    query_shape: dict[str, Any] | None = None,
) -> None:
    """发送 chat_message_sent 事件。对应原项目 trackChatEvent。

    非云端部署或未配置时静默跳过。发送失败只记日志,不抛异常。
    """
    client = _get_client()
    if client is None:
        return

    properties: dict[str, Any] = {
        "searchMode": search_mode,
        "conversationTurn": conversation_turn,
        "isNewChat": is_new_chat,
        "trigger": trigger,
        "chatId": chat_id,
        "isGuest": is_guest,
        "providerId": provider_id,
        "modelId": model_id,
    }
    if user_id:
        properties["userId"] = user_id
    if query_shape:
        properties.update(query_shape)

    try:
        client.capture(
            distinct_id=distinct_id,
            event="chat_message_sent",
            properties=properties,
        )
    except Exception:
        logger.exception("PostHog 事件发送失败")


def shutdown_analytics() -> None:
    """关闭 PostHog 客户端,冲刷缓冲事件。应用关闭时调用。"""
    if _client is not None:
        try:
            _client.shutdown()
        except Exception:
            logger.exception("PostHog shutdown 失败")
