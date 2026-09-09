"""聊天接口:POST /api/chat。

设计意图:
    对应原项目 app/api/chat/route.ts。阶段 3 先打通"最小闭环":
    接收一条用户消息 → 驱动 Quick 模式智能体 → 以 SSE 流式返回回答。
    历史持久化、认证、限流在阶段 4/5 接入;本路由先聚焦"流能正确产出"。

    请求体沿用前端 useChat 的实际格式:
      { "message": {"parts":[{"type":"text","text":"..."}]}, "chatId": "...", ... }
    响应为 text/event-stream,帧格式严格遵循 packages/protocol/PROTOCOL.md。
"""

import asyncio

from fastapi import APIRouter, Header, Request
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel

from ryoshi.agents.models import ModelConfigError, adefault_model_id
from ryoshi.agents.researcher import create_quick_researcher
from ryoshi.auth import resolve_user
from ryoshi.chat.frames import Error
from ryoshi.chat.sse import SSE_HEADERS, encode_done, encode_frame
from ryoshi.chat.stream import agent_stream_to_frames
from ryoshi.db.engine import get_session_factory
from ryoshi.db.persistence import create_chat_with_first_message, upsert_message

router = APIRouter(prefix="/api", tags=["chat"])

# 后台兜底持久化任务的引用池:防止 fire-and-forget 任务被 GC 中途取消
# (asyncio 官方建议的 create_task 模式),任务完成后自动移出。
_BACKGROUND_PERSIST_TASKS: set[asyncio.Task] = set()


# 真实客户端 IP 提取见 ratelimit.client_ip_from_request(XFF 取末位条目,
# 首位可被客户端伪造;裸跑时回退 request.client.host)


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


# 已知"不支持图片输入"的模型名模式(小写子串匹配)。
# 判定策略:已知不支持 → 降级;已知支持 → 放行;未知名 → 放行
# (新模型大多支持视觉,且 API 报错比静默丢图更诚实)。
_NO_VISION_PATTERNS = (
    "deepseek-chat",       # DeepSeek V 系列文本模型(reasoner 同样不支持图)
    "deepseek-reasoner",
    "gpt-4o-mini-audio",   # 音频变体
    "o1-mini",             # 纯文本推理模型
    "text-embedding",      # embedding 系(防御性)
)

_VISION_PATTERNS = (
    "gpt-4o", "gpt-4.1", "gpt-5", "gpt-4-turbo",
    "claude-3", "claude-4", "claude-opus", "claude-sonnet", "claude-haiku",
    "gemini-",  # Gemini 全系原生多模态
    "qwen-vl", "qwen2-vl", "qvq", "glm-4v",
)


def _supports_vision(model_name: str) -> bool:
    """按模型名判断是否支持图片输入(启发式清单,未知默认支持)。"""
    name = model_name.lower()
    if any(p in name for p in _NO_VISION_PATTERNS):
        return False
    return True


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
            texts.append(
                f"[附件: {p.get('filename', 'file')} ({p.get('mediaType', '')})]({p['url']})"
            )
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
    user = await resolve_user(authorization, allow_anonymous_fallback=True)
    user_text = _extract_user_text(req)

    # ---- 模型校验(在限流之前,避免模型错误浪费限流额度) ----
    # 模型选择:优先用前端 cookie 中的选择,无效则回退默认模型
    # 对应原项目 lib/utils/model-selection.ts 的 cookie 读取逻辑。
    # BYOK:登录用户用其私有密钥判定可用性与默认模型;匿名只看环境变量。
    byok_user_id = None if user.is_anonymous else user.id
    try:
        if req.modelId:
            # 校验格式: provider:model
            if ":" not in req.modelId:
                raise ModelConfigError(f"模型标识缺少 provider 前缀: {req.modelId!r}")

            provider_id, model_id_part = req.modelId.split(":", 1)
            if not provider_id or not model_id_part:
                raise ModelConfigError(f"模型标识格式无效: {req.modelId!r}")

            # 校验 provider 可用(有密钥)
            from ryoshi.agents.models import ais_provider_enabled

            if not await ais_provider_enabled(provider_id, byok_user_id):
                raise ModelConfigError(f"provider 未启用: {provider_id}")

            # 校验 modelId 在白名单内(防止恶意调用未声明的模型)
            from ryoshi.agents.models import _resolve_credentials

            creds = await _resolve_credentials(provider_id, byok_user_id)
            if creds is not None and creds.models:
                allowed_models = [m.strip() for m in creds.models.split(",") if m.strip()]
                if model_id_part not in allowed_models:
                    raise ModelConfigError(
                        f"模型 {model_id_part} 不在允许列表中。"
                        f"可用模型: {', '.join(allowed_models)}"
                    )

            model_id = req.modelId
        else:
            model_id = await adefault_model_id(byok_user_id)
    except ModelConfigError as exc:
        # 未配置任何模型密钥:返回规范 error 帧而非裸 500,前端能统一展示。
        # 注意:except 的 exc 在块结束后会被解释器删除,闭包须先存到局部变量。
        error_message = str(exc)

        async def no_model():
            yield encode_frame(Error(errorText=error_message))
            yield encode_done()

        return StreamingResponse(no_model(), headers=SSE_HEADERS)

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
                "error": (
                    "Sign in to use Adaptive mode. Quick mode remains available without an account."
                ),
                "mode": "adaptive",
                "authRequired": True,
            },
        )

    # 1. 访客限流(未登录时按 IP)
    if user.is_anonymous:
        from ryoshi.ratelimit import client_ip_from_request

        client_ip = client_ip_from_request(request)
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
                    "error": (
                        "Daily limit for Adaptive mode reached. "
                        "Please try again tomorrow, or continue in Quick mode."
                    ),
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

    # ---- 会话写权限校验(防分享链接越权写) ----
    # 对应原项目两处防御的应用层等价物:分享页禁聊(route.ts 403)+ RLS。
    # visibility='public' 的会话任何人可读,但只有 owner 能继续提问;
    # 否则拿到分享链接的人就能往别人会话里追加消息。
    if not req.isNewChat and req.chatId:
        from ryoshi.db.persistence import check_chat_write_permission

        async with get_session_factory()() as session:
            allowed = await check_chat_write_permission(session, req.chatId, user.id)
        if not allowed:
            return JSONResponse(
                status_code=403,
                content={"error": "You do not have permission to write to this chat."},
            )

    # ---- regenerate 清理:删除被替换的旧消息及其后全部消息 ----
    # AI SDK 前端在本地把消息列表截断到目标消息之前再发请求;后端若不
    # 同步删除,旧回答留在库里,刷新页面后会"复活"(与前端显示不一致)。
    # messageId 可能是 assistant 消息(重试回答)或 user 消息(编辑重发)。
    # 删除必须在 build_model_messages 之前——模型输入的历史从 DB 加载,
    # 顺序对了被删内容自然不会进入上下文。
    if req.trigger == "regenerate-message" and req.messageId and req.chatId:
        from ryoshi.db.persistence import delete_message_and_after

        async with get_session_factory()() as session:
            await delete_message_and_after(session, req.chatId, req.messageId)

    # 按 searchMode 选择智能体:quick(默认)或 adaptive
    if req.searchMode == "adaptive":
        from ryoshi.agents.researcher import create_adaptive_researcher
        agent = await create_adaptive_researcher(model_id, byok_user_id)
        max_steps = 50  # 对应原项目 adaptive maxSteps=50
    else:
        agent = await create_quick_researcher(model_id, byok_user_id)
        max_steps = 20  # 对应原项目 quick maxSteps=20

    # ---- 构造模型输入:历史消息 + 当前消息,再按上下文窗口截断 ----
    # 对应原项目 prepareMessages:非新聊天时从 DB 加载历史并追加当前消息。
    from ryoshi.chat.context_window import get_max_allowed_tokens, truncate_messages
    from ryoshi.db.persistence import load_chat

    def _multimodal_content(text: str, parts: list[dict] | None):
        """把当前用户消息构造成模型 content:有图片附件时输出多模态 block 列表。

        LangChain 的 {"type": "image_url", "image_url": {"url": ...}} 是
        标准多模态形态,openai/anthropic/google 各家客户端会自动归一成
        自己的 API 格式(anthropic 的 base64/source、google 的 file_data)。
        只处理"当前这条消息"的附件:历史轮次的图片重新喂入意义有限
        (追问通常围绕最新图片),且旧消息的 file url 可能已过期。

        注意 _extract_user_text 已把附件写成 "[附件: xxx](url)" 文本行,
        多模态 block 与它并存:文本行让模型知道附件的存在与文件名,
        image_url block 让模型真正"看到"图片内容。

        视觉能力检测:不支持图片的模型(如 deepseek-chat)收到
        image_url block 会直接 API 报错。按模型名模式判断(BYOK 自定义
        id 无法穷举,宁可保守:未知名默认尝试发送——多数新模型支持,
        失败时错误信息也远比静默丢弃友好)。
        """
        image_parts = [
            p for p in (parts or [])
            if p.get("type") == "file"
            and str(p.get("mediaType", "")).startswith("image/")
            and p.get("url")
        ]
        if not image_parts:
            return text  # 无图片附件:维持纯文本,行为与之前完全一致

        model_name = model_id.split(":", 1)[1] if ":" in model_id else model_id
        if not _supports_vision(model_name):
            # 降级:模型看不了图,给明确文本说明而非 API 报错
            names = ", ".join(str(p.get("filename", "图片")) for p in image_parts)
            hint = f"\n\n[系统提示:当前模型不支持图片输入,用户上传了 {len(image_parts)} 张图片({names})但无法查看。请如实告知这一限制。]"
            return text + hint

        blocks: list[dict] = []
        if text:
            blocks.append({"type": "text", "text": text})
        blocks.extend(
            {"type": "image_url", "image_url": {"url": p["url"]}}
            for p in image_parts
        )
        return blocks

    async def build_model_messages() -> list:
        """组装传给智能体的 LangChain 消息列表(含历史,已截断)。"""
        from langchain_core.messages import AIMessage, HumanMessage

        history: list = []
        if not req.isNewChat and req.chatId:
            async with get_session_factory()() as session:
                chat = await load_chat(session, req.chatId)
            if chat:
                for m in chat["messages"]:
                    text = "".join(
                        p.get("text", "") for p in m.get("parts", []) if p.get("type") == "text"
                    )
                    if not text:
                        continue
                    if m["role"] == "user":
                        history.append(HumanMessage(content=text))
                    elif m["role"] == "assistant":
                        history.append(AIMessage(content=text))

        # 当前用户消息放最后;带图片附件时构造多模态 content
        current_parts = req.message.parts if req.message else None
        history.append(
            HumanMessage(content=_multimodal_content(user_text, current_parts))
        )

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

    async def _persist_partial(partial: dict) -> None:
        """兜底持久化(后台任务):中断的回答落库,失败仅记日志。

        闭包捕获的 chat_id / persist_assistant_message 与流内路径完全一致,
        upsert 幂等(同 id 覆盖),即使与流内持久化竞争也无害。
        """
        try:
            await persist_assistant_message(partial)
        except Exception as exc:
            print(f"[ryoshi] 中断回答的兜底持久化失败: {exc}")

    async def _maybe_refresh_title() -> None:
        """新会话首答完成后,后台生成 LLM 标题(对应原项目 title-generator)。

        fire-and-forget:不阻塞 SSE;失败保留首条消息截断的兜底标题。
        """
        if not (req.isNewChat and chat_id and user_text.strip()):
            return
        from ryoshi.agents.title import refresh_chat_title

        await refresh_chat_title(chat_id, user_text, model_id, byok_user_id)

    async def event_stream():
        # 先落用户消息(失败不阻塞流式,只记日志——历史缺失可容忍,回答必须送达)
        try:
            await persist_user_message()
        except Exception as exc:
            print(f"[ryoshi] 用户消息持久化失败: {exc}")

        # Langfuse trace:整个研究过程包在一个 trace 里,traceId 写入消息 metadata,
        # 前端反馈按钮据此关联评分(对应原项目 traceId 贯穿 researcher + title-gen)。
        from ryoshi.observability.tracing import research_trace

        # 流句柄:客户端断开时,stream 生成器无法在自己的 finally 里持久化
        # (async generator 被 aclose 后禁止 await),把部分消息快照挂到这里,
        # 由本函数的 finally 兜底落库。见 chat/stream.py 尾部注释。
        stream_handle: dict = {}

        try:
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
                    stream_handle=stream_handle,
                )
                async for frame in frames:
                    yield encode_frame(frame)
                yield encode_done()

            # 新会话:回答已落库,后台生成 LLM 标题(fire-and-forget,
            # 与兜底持久化共用引用池防 GC)。放 finally 之外——只在
            # 正常完成时触发,中断/出错的会话保留兜底标题即可。
            title_task = asyncio.create_task(_maybe_refresh_title())
            _BACKGROUND_PERSIST_TASKS.add(title_task)
            title_task.add_done_callback(_BACKGROUND_PERSIST_TASKS.discard)
        finally:
            # 正常/出错路径已由 stream 内部回调持久化(persisted=True);
            # 客户端断开(点"停止"/网络闪断)时 GeneratorExit/CancelledError
            # 穿透 async for 走到这里——用快照把"答了一半"的内容落库。
            # 必须用 create_task 而非 await:本函数也是 async generator,
            # 断开路径的 finally 里挂起等待会触发
            # "async generator ignored GeneratorExit" 或被取消作用域二次取消;
            # 发射一个独立任务不挂起,两种断开路径都成立。
            partial = stream_handle.get("partial_message")
            if partial and not stream_handle.get("persisted") and partial["parts"]:
                task = asyncio.create_task(_persist_partial(partial))
                # 持引用防 GC(asyncio 官方建议的 fire-and-forget 模式)
                _BACKGROUND_PERSIST_TASKS.add(task)
                task.add_done_callback(_BACKGROUND_PERSIST_TASKS.discard)

    return StreamingResponse(event_stream(), headers=SSE_HEADERS)
