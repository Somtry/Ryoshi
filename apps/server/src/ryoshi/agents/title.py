"""LLM 会话标题生成(对应原项目 lib/agents/title-generator.ts)。

设计意图:
    会话标题原本直接取首条用户消息截断 255 字,侧栏里长问题挤成一团。
    原项目用小模型生成 3~5 词标题;Ryoshi 沿用该策略,但做了三点适配:
      1. fire-and-forget:标题生成在回答落库后后台执行,不阻塞 SSE 流
         (用户提问到首字响应的路径上不引入任何额外延迟)
      2. 失败静默:模型不可用/超时,保留"首条消息截断"的原标题兜底
      3. 复用主对话模型:不引入独立"小模型"配置(原项目用同一个
         modelId 生成);生成参数 max_tokens=24 强制简短
"""

import logging

logger = logging.getLogger("ryoshi.title")

# 标题生成 system prompt(与原项目逐条对应;强调跟随消息语言)
_TITLE_PROMPT = (
    "You are an AI assistant specialized in creating very short, concise, "
    "and informative titles for chat conversations based on the user's first "
    "message. The title should ideally be 3-5 words long, and no more than "
    "10 words. Respond in the same language as the user's message. "
    "Only output the title itself, with no prefixes, labels, or quotation marks."
)

# 生成 token 上限:10 个词的标题无论如何用不到更多
_MAX_TOKENS = 24

# 标题长度上限(chats.title 的合理语义值;中文约 20 字)
_TITLE_MAX_CHARS = 50

# 兜底标题:首条消息截断长度(与原项目 fallbackTitle 一致)
_FALLBACK_CHARS = 75

# 标题生成超时:小输出,30 秒足够;超时保留兜底标题
_TIMEOUT_SECONDS = 30.0


def fallback_title(user_message: str) -> str:
    """兜底标题:首条消息截断(与原项目一致)。"""
    return (user_message or "").strip()[:_FALLBACK_CHARS] or "New Chat"


async def generate_chat_title(
    user_message: str, model_id: str, user_id: str | None
) -> str:
    """为首条用户消息生成简短标题。

    参数:
        user_message: 首条用户消息文本
        model_id: "providerId:modelId"(与主对话一致)
        user_id: BYOK 用户 id(匿名传 None)
    返回:
        生成的标题;失败时返回首条消息截断兜底。
    """
    fallback = fallback_title(user_message)

    try:
        import asyncio

        from ryoshi.agents.models import aget_model

        model = await aget_model(model_id, user_id)
        result = await asyncio.wait_for(
            model.ainvoke(
                [
                    ("system", _TITLE_PROMPT),
                    ("human", user_message[:2000]),  # 标题不需要全文
                ],
                max_tokens=_MAX_TOKENS,
                temperature=0.3,  # 低温度:标题要稳定不要创意
            ),
            timeout=_TIMEOUT_SECONDS,
        )
        title = str(result.content or "").strip()
        # 剥模型偶尔添加的引号/书名号(中西文全算)
        title = title.strip("".join(['"', "'", chr(0x201C), chr(0x201D), chr(0x2018), chr(0x2019), chr(0x300A), chr(0x300B), " "]))
        if not title:
            return fallback
        return title[:_TITLE_MAX_CHARS]
    except Exception as exc:
        logger.info(f"标题生成失败({type(exc).__name__}),使用兜底截断")
        return fallback


async def refresh_chat_title(
    chat_id: str, first_user_message: str, model_id: str, user_id: str | None
) -> None:
    """后台任务入口:生成标题并更新 chats.title。

    供 chat 路由以 asyncio.create_task fire-and-forget 调用。
    独立开 DB 会话(不与请求会话共享);只更新仍为"兜底形态"的标题
    (首条消息截断)——避免覆盖用户将来可能的手动改名。
    任何失败只记日志。
    """
    try:
        from ryoshi.db.engine import get_session_factory
        from ryoshi.db.models import Chat

        # 先生成再开事务:生成耗时(秒级),不能占着连接
        new_title = await generate_chat_title(first_user_message, model_id, user_id)

        async with get_session_factory()() as session:
            chat = await session.get(Chat, chat_id)
            if chat is None:
                return
            # 只有当前标题仍是兜底形态(长截断)才覆盖;已是短标题(说明
            # 之前生成过或用户改过)则不动
            if len(chat.title) <= _TITLE_MAX_CHARS:
                return
            chat.title = new_title
            await session.commit()
    except Exception:
        logger.exception("会话标题后台更新失败")
