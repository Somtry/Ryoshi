"""聊天接口:POST /api/chat。

设计意图:
    对应原项目 app/api/chat/route.ts。阶段 3 先打通"最小闭环":
    接收一条用户消息 → 驱动 Quick 模式智能体 → 以 SSE 流式返回回答。
    历史持久化、认证、限流在阶段 4/5 接入;本路由先聚焦"流能正确产出"。

    请求体沿用前端 useChat 的实际格式:
      { "message": {"parts":[{"type":"text","text":"..."}]}, "chatId": "...", ... }
    响应为 text/event-stream,帧格式严格遵循 packages/protocol/PROTOCOL.md。
"""

from fastapi import APIRouter, Header, Request
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel

from ryoshi.agents.models import ModelConfigError, default_model_id
from ryoshi.agents.researcher import create_quick_researcher
from ryoshi.auth import resolve_user
from ryoshi.chat.frames import Error
from ryoshi.chat.sse import SSE_HEADERS, encode_done, encode_frame
from ryoshi.chat.stream import agent_stream_to_frames
from ryoshi.db.engine import get_session_factory
from ryoshi.db.persistence import create_chat_with_first_message, upsert_message

router = APIRouter(prefix="/api", tags=["chat"])


class TextPart(BaseModel):
    type: str
    text: str | None = None


class FilePart(BaseModel):
    """用户上传的附件(图片/PDF)。"""

    type: str  # "file"
    url: str | None = None
    filename: str | None = None
    mediaType: str | None = None
    key: str | None = None


class DataPart(BaseModel):
    """自定义数据部件(粘贴内容/引用上下文/笔记/目标 URL)。"""

    type: str  # "data-pastedContent" / "data-quotedContext" / ...
    data: dict | None = None
    id: str | None = None


class IncomingMessage(BaseModel):
    """前端 useChat 提交的用户消息。parts 包含文本/文件/数据部件。"""

    id: str | None = None
    role: str = "user"
    parts: list[dict] = []  # 宽接:dict 保留全部字段,后续按 type 分派


class ChatRequest(BaseModel):
    message: IncomingMessage | None = None
    chatId: str | None = None
    searchMode: str = "quick"
    # 前端在首轮提交时置 true,后端据此建会话(从首条消息生成标题)
    isNewChat: bool = False
    # 用户选择的模型(cookie 中的 selectedModel,格式 "providerId:modelId")
    modelId: str | None = None
    # 前端传的 trigger(submit-message / regenerate-message)
    trigger: str = "submit-message"
    # regenerate 时要重新生成的消息 id
    messageId: str | None = None
    # PostHog 匿名 ID(未登录用户的事件归属)
    analyticsId: str | None = None
    # 匿名模式下前端把全部历史消息发过来(对应原项目 prepareMessages 的 messages)
    messages: list[IncomingMessage] = []


def _extract_user_text(req: ChatRequest) -> str:
    """从消息 parts 抽出纯文本(拼接 text 部件 + 文件引用 + 数据部件中的文本)。"""
    if not req.message:
        return ""
    parts = req.message.parts
    texts: list[str] = []
    for p in parts:
        ptype = p.get("type", "")
        if ptype == "text" and p.get("text"):
            texts.append(p["text"])
        elif ptype == "file" and p.get("url"):
            # 文件附件:把 URL 和类型注入上下文,让模型知道有附件
            texts.append(f"[附件: {p.get('filename', 'file')} ({p.get('mediaType', '')})]({p['url']})")
        elif ptype == "data-pastedContent" and p.get("data"):
            # 粘贴的大段内容
            content = p["data"].get("content", "") if isinstance(p["data"], dict) else ""
            if content:
                texts.append(content)
        elif ptype == "data-quotedContext" and p.get("data"):
            # 引用的上文
            content = p["data"].get("content", "") if isinstance(p["data"], dict) else ""
            if content:
                texts.append(f"> {content}")
        elif ptype == "data-sourceUrl" and p.get("data"):
            # 用户指定的目标 URL
            url = p["data"].get("url", "") if isinstance(p["data"], dict) else ""
            if url:
                texts.append(f"请分析这个页面: {url}")
    return "\n".join(texts)


@router.post("/chat", response_model=None)
async def chat(
    req: ChatRequest,
    request: Request,
    authorization: str | None = Header(None),
) -> StreamingResponse | JSONResponse:
    """处理一次提问并流式返回回答。"""
    # 认证:ENABLE_AUTH=false 时匿名;ENABLE_AUTH=true 时校验 JWT,
    # 未登录但允许匿名回退(对应原项目"未登录也可提问"的行为)
    user = resolve_user(authorization, allow_anonymous_fallback=True)
    user_text = _extract_user_text(req)

    # ---- 三层限流(仅云端部署生效) ----
    # 对应原项目 app/api/chat/route.ts 的限流检查顺序:
    # 访客 IP → 用户总量 → adaptive 单独
    # 0. Adaptive 模式在云端需要登录(对齐原型 route.ts:113-134)
    from ryoshi.config import get_settings as _get_settings
    from ryoshi.ratelimit import (
        check_adaptive_limit,
        check_guest_limit,
        check_overall_chat_limit,
    )

    if (
        req.searchMode == "adaptive"
        and user.is_anonymous
        and _get_settings().ryoshi_cloud_deployment
    ):
        return JSONResponse(
            status_code=401,
            content={
                "error": "Sign in to use Adaptive mode. Quick mode remains available without an account.",
                "mode": "adaptive",
                "authRequired": True,
            },
        )

    # 1. 访客限流(未登录时按 IP)
    if user.is_anonymous:
        client_ip = request.client.host if request.client else None
        if client_ip:
            guest_result = await check_guest_limit(client_ip)
            if not guest_result.allowed:
                return JSONResponse(
                    status_code=401,
                    content={
                        "error": "Please sign in to continue.",
                        "authRequired": True,
                        "remaining": 0,
                        "resetAt": guest_result.reset_at,
                        "limit": guest_result.limit,
                    },
                    headers={
                        "X-RateLimit-Limit": str(guest_result.limit),
                        "X-RateLimit-Remaining": "0",
                        "X-RateLimit-Reset": str(guest_result.reset_at),
                    },
                )

    # 2. 用户总量限流(登录用户按 userId)
    if not user.is_anonymous:
        overall_result = await check_overall_chat_limit(user.id)
        if not overall_result.allowed:
            return JSONResponse(
                status_code=429,
                content={
                    "error": "Daily chat limit reached. Please try again tomorrow.",
                    "remaining": 0,
                    "resetAt": overall_result.reset_at,
                    "limit": overall_result.limit,
                },
                headers={
                    "X-RateLimit-Limit": str(overall_result.limit),
                    "X-RateLimit-Remaining": "0",
                    "X-RateLimit-Reset": str(overall_result.reset_at),
                },
            )

    # 3. Adaptive 模式单独限流
    if req.searchMode == "adaptive" and not user.is_anonymous:
        adaptive_result = await check_adaptive_limit(user.id)
        if not adaptive_result.allowed:
            return JSONResponse(
                status_code=429,
                content={
                    "error": "Daily limit for Adaptive mode reached. Please try again tomorrow, or continue in Quick mode.",
                    "mode": "adaptive",
                    "remaining": 0,
                    "resetAt": adaptive_result.reset_at,
                    "limit": adaptive_result.limit,
                },
                headers={
                    "X-RateLimit-Limit": str(adaptive_result.limit),
                    "X-RateLimit-Remaining": "0",
                    "X-RateLimit-Reset": str(adaptive_result.reset_at),
                },
            )
    if not user_text.strip():
        # 空消息直接返回一个最小 SSE 流并结束,避免驱动智能体
        async def empty():
            yield encode_done()

        return StreamingResponse(empty(), headers=SSE_HEADERS)

    # 模型选择:优先用前端 cookie 中的选择,无效则回退默认模型
    # 对应原项目 lib/utils/model-selection.ts 的 cookie 读取逻辑
    try:
        if req.modelId:
            # 校验 provider 可用(有密钥),不可用则抛 ModelConfigError
            from ryoshi.agents.models import is_provider_enabled

            provider_id = req.modelId.split(":")[0] if ":" in req.modelId else ""
            if not is_provider_enabled(provider_id):
                raise ModelConfigError(f"provider 未启用: {provider_id}")
            model_id = req.modelId
        else:
            model_id = default_model_id()
    except ModelConfigError as exc:
        # 未配置任何模型密钥:返回规范 error 帧而非裸 500,前端能统一展示。
        # 注意:except 的 exc 在块结束后会被解释器删除,闭包须先存到局部变量。
        error_message = str(exc)

        async def no_model():
            yield encode_frame(Error(errorText=error_message))
            yield encode_done()

        return StreamingResponse(no_model(), headers=SSE_HEADERS)

    # 按 searchMode 选择智能体:quick(默认)或 adaptive
    if req.searchMode == "adaptive":
        from ryoshi.agents.researcher import create_adaptive_researcher
        agent = create_adaptive_researcher(model_id)
        max_steps = 50  # 对应原项目 adaptive maxSteps=50
    else:
        agent = create_quick_researcher(model_id)
        max_steps = 20  # 对应原项目 quick maxSteps=20

    # ---- 构造模型输入:历史消息 + 当前消息,再按上下文窗口截断 ----
    # 对应原项目 prepareMessages:非新聊天时从 DB 加载历史并追加当前消息。
    from ryoshi.chat.context_window import get_max_allowed_tokens, truncate_messages
    from ryoshi.db.persistence import load_chat

    async def build_model_messages() -> list:
        """组装传给智能体的 LangChain 消息列表(含历史,已截断)。"""
        from langchain_core.messages import AIMessage, HumanMessage

        history: list = []
        if not req.isNewChat and req.chatId:
            async with get_session_factory()() as session:
                chat = await load_chat(session, req.chatId)
            if chat:
                for m in chat["messages"]:
                    text = "".join(p.get("text", "") for p in m.get("parts", []) if p.get("type") == "text")
                    if not text:
                        continue
                    if m["role"] == "user":
                        history.append(HumanMessage(content=text))
                    elif m["role"] == "assistant":
                        history.append(AIMessage(content=text))

        # 当前用户消息放最后
        history.append(HumanMessage(content=user_text))

        # 上下文窗口截断(对应原项目 truncateMessages)
        model_name = model_id.split(":", 1)[1] if ":" in model_id else model_id
        return truncate_messages(history, get_max_allowed_tokens(model_name), model_name)

    messages = await build_model_messages()

    # ---- PostHog 分析:仅云端部署发送;fire-and-forget,不阻塞聊天 ----
    # 对应原项目 app/api/chat/route.ts 的 trackChatEvent 调用。
    from ryoshi.observability.analytics import (
        calculate_conversation_turn,
        derive_query_shape,
        track_chat_event,
    )

    try:
        # distinctId: 登录用户用 user_id,匿名用前端传的 analyticsId
        distinct_id = (
            user.id
            if not user.is_anonymous
            else req.analyticsId or user.id
        )
        # 对话轮次:新聊天为 1;否则数历史中的 user 消息条数
        conversation_turn = 1
        if not req.isNewChat and req.chatId:
            # 简化:用 messages 数组长度估算(匿名模式前端会传 messages)
            history_user_ids = (
                [m.get("id", "") for m in req.messages if m.role == "user"]
                if req.messages
                else []
            )
            conversation_turn = calculate_conversation_turn(
                history_user_ids,
                req.message.id if req.message else None,
            )

        provider_id = model_id.split(":", 1)[0] if ":" in model_id else model_id
        track_chat_event(
            search_mode=req.searchMode,
            conversation_turn=conversation_turn,
            is_new_chat=req.isNewChat,
            trigger=req.trigger,
            chat_id=req.chatId or "",
            distinct_id=distinct_id,
            is_guest=user.is_anonymous,
            user_id=None if user.is_anonymous else user.id,
            provider_id=provider_id,
            model_id=model_id.split(":", 1)[1] if ":" in model_id else model_id,
            query_shape=derive_query_shape(user_text),
        )
    except Exception:
        pass  # 分析失败不影响聊天

    # ---- 持久化:先落用户消息,流结束后再落 assistant 回答 ----
    # 对应原项目 persistStreamResults:新聊天先建会话+首消息,
    # 已有聊天只追加用户消息;assistant 回答在流完整结束后落库。
    user_id = user.id  # 来自 JWT 或匿名回退(见函数开头 resolve_user)
    chat_id = req.chatId

    async def persist_user_message() -> None:
        """把用户消息落库。新聊天顺带建会话(从首条消息生成标题)。

        parts 直接透传 dict(不经过 TextPart/FilePart 等窄化模型),
        保留 file/data 部件的完整字段(url/filename/mediaType 等)。
        """
        if not chat_id or not req.message:
            return
        user_msg = {
            "id": req.message.id,
            "role": "user",
            "parts": req.message.parts,  # 已是 list[dict],直接透传
            "metadata": None,
        }
        async with get_session_factory()() as session:
            if req.isNewChat:
                await create_chat_with_first_message(session, chat_id, user_msg, user_id)
            else:
                await upsert_message(session, chat_id, user_msg)

    async def persist_assistant_message(assistant_msg: dict) -> None:
        """流结束后把 assistant 回答落库(含工具调用与文本部件)。"""
        if not chat_id:
            return
        async with get_session_factory()() as session:
            await upsert_message(session, chat_id, assistant_msg)

    async def event_stream():
        # 先落用户消息(失败不阻塞流式,只记日志——历史缺失可容忍,回答必须送达)
        try:
            await persist_user_message()
        except Exception as exc:
            print(f"[ryoshi] 用户消息持久化失败: {exc}")

        # Langfuse trace:整个研究过程包在一个 trace 里,traceId 写入消息 metadata,
        # 前端反馈按钮据此关联评分(对应原项目 traceId 贯穿 researcher + title-gen)。
        from ryoshi.observability.tracing import research_trace

        async with research_trace(chat_id or "", user_id, model_id, req.searchMode) as trace_id:
            metadata: dict = {"searchMode": req.searchMode, "modelId": model_id}
            if trace_id:
                metadata["traceId"] = trace_id

            frames = agent_stream_to_frames(
                agent,
                messages,
                # message_id 是 assistant 回答的 id,必须新建;复用 req.message.id
                # (用户消息 id)会让前端把用户消息覆盖掉,故这里不传,由流内生成。
                message_metadata=metadata,
                on_assistant_message=persist_assistant_message,
                max_steps=max_steps,
            )
            async for frame in frames:
                yield encode_frame(frame)
            yield encode_done()

    return StreamingResponse(event_stream(), headers=SSE_HEADERS)
