"""聊天接口:POST /api/chat。

设计意图:
    对应原项目 app/api/chat/route.ts。阶段 3 先打通"最小闭环":
    接收一条用户消息 → 驱动 Quick 模式智能体 → 以 SSE 流式返回回答。
    历史持久化、认证、限流在阶段 4/5 接入;本路由先聚焦"流能正确产出"。

    请求体沿用前端 useChat 的实际格式:
      { "message": {"parts":[{"type":"text","text":"..."}]}, "chatId": "...", ... }
    响应为 text/event-stream,帧格式严格遵循 packages/protocol/PROTOCOL.md。
"""

from fastapi import APIRouter, Header
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from ryoshi.agents.models import ModelConfigError, default_model_id
from ryoshi.agents.researcher import build_initial_messages, create_quick_researcher
from ryoshi.auth import AuthUser, resolve_user
from ryoshi.chat.frames import Error
from ryoshi.chat.sse import SSE_HEADERS, encode_done, encode_frame
from ryoshi.chat.stream import agent_stream_to_frames
from ryoshi.config import get_settings
from ryoshi.db.engine import get_session_factory
from ryoshi.db.persistence import create_chat_with_first_message, upsert_message

router = APIRouter(prefix="/api", tags=["chat"])


class TextPart(BaseModel):
    type: str
    text: str | None = None


class IncomingMessage(BaseModel):
    """前端 useChat 提交的用户消息。parts 里取文本即可(附件在阶段 4 处理)。"""

    id: str | None = None
    role: str = "user"
    parts: list[TextPart] = []


class ChatRequest(BaseModel):
    message: IncomingMessage | None = None
    chatId: str | None = None
    searchMode: str = "quick"
    # 前端在首轮提交时置 true,后端据此建会话(从首条消息生成标题)
    isNewChat: bool = False
    # 匿名模式下前端把全部历史消息发过来(对应原项目 prepareMessages 的 messages)
    messages: list[IncomingMessage] = []


def _extract_user_text(req: ChatRequest) -> str:
    """从消息 parts 抽出纯文本(拼接所有 text 部件)。"""
    if not req.message:
        return ""
    return "\n".join(p.text for p in req.message.parts if p.type == "text" and p.text)


@router.post("/chat")
async def chat(
    req: ChatRequest, authorization: str | None = Header(None)
) -> StreamingResponse:
    """处理一次提问并流式返回回答。"""
    # 认证:ENABLE_AUTH=false 时匿名;ENABLE_AUTH=true 时校验 JWT,
    # 未登录但允许匿名回退(对应原项目"未登录也可提问"的行为)
    user = resolve_user(authorization, allow_anonymous_fallback=True)
    user_text = _extract_user_text(req)
    if not user_text.strip():
        # 空消息直接返回一个最小 SSE 流并结束,避免驱动智能体
        async def empty():
            yield encode_done()

        return StreamingResponse(empty(), headers=SSE_HEADERS)

    # 阶段 3 固定用 Quick 模式与默认模型;模型选择/searchMode 在阶段 4 接入 cookie 逻辑
    try:
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

    # ---- 持久化:先落用户消息,流结束后再落 assistant 回答 ----
    # 对应原项目 persistStreamResults:新聊天先建会话+首消息,
    # 已有聊天只追加用户消息;assistant 回答在流完整结束后落库。
    user_id = user.id  # 来自 JWT 或匿名回退(见函数开头 resolve_user)
    chat_id = req.chatId

    async def persist_user_message() -> None:
        """把用户消息落库。新聊天顺带建会话(从首条消息生成标题)。"""
        if not chat_id or not req.message:
            return
        user_msg = {
            "id": req.message.id,
            "role": "user",
            "parts": [p.model_dump() for p in req.message.parts],
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
        except Exception as exc:  # noqa: BLE001
            print(f"[ryoshi] 用户消息持久化失败: {exc}")

        frames = agent_stream_to_frames(
            agent,
            messages,
            # message_id 是 assistant 回答的 id,必须新建;复用 req.message.id
            # (用户消息 id)会让前端把用户消息覆盖掉,故这里不传,由流内生成。
            message_metadata={"searchMode": req.searchMode, "modelId": model_id},
            on_assistant_message=persist_assistant_message,
            max_steps=max_steps,
        )
        async for frame in frames:
            yield encode_frame(frame)
        yield encode_done()

    return StreamingResponse(event_stream(), headers=SSE_HEADERS)
