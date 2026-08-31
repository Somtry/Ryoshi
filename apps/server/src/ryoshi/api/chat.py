"""聊天接口:POST /api/chat。

设计意图:
    对应原项目 app/api/chat/route.ts。阶段 3 先打通"最小闭环":
    接收一条用户消息 → 驱动 Quick 模式智能体 → 以 SSE 流式返回回答。
    历史持久化、认证、限流在阶段 4/5 接入;本路由先聚焦"流能正确产出"。

    请求体沿用前端 useChat 的实际格式:
      { "message": {"parts":[{"type":"text","text":"..."}]}, "chatId": "...", ... }
    响应为 text/event-stream,帧格式严格遵循 packages/protocol/PROTOCOL.md。
"""

from fastapi import APIRouter
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from ryoshi.agents.models import ModelConfigError, default_model_id
from ryoshi.agents.researcher import build_initial_messages, create_quick_researcher
from ryoshi.chat.frames import Error
from ryoshi.chat.sse import SSE_HEADERS, encode_done, encode_frame
from ryoshi.chat.stream import agent_stream_to_frames

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


def _extract_user_text(req: ChatRequest) -> str:
    """从消息 parts 抽出纯文本(拼接所有 text 部件)。"""
    if not req.message:
        return ""
    return "\n".join(p.text for p in req.message.parts if p.type == "text" and p.text)


@router.post("/chat")
async def chat(req: ChatRequest) -> StreamingResponse:
    """处理一次提问并流式返回回答。"""
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

    agent = create_quick_researcher(model_id)
    messages = build_initial_messages(user_text)

    async def event_stream():
        frames = agent_stream_to_frames(
            agent,
            messages,
            # message_id 是 assistant 回答的 id,必须新建;复用 req.message.id
            # (用户消息 id)会让前端把用户消息覆盖掉,故这里不传,由流内生成。
            message_metadata={"searchMode": req.searchMode, "modelId": model_id},
        )
        async for frame in frames:
            yield encode_frame(frame)
        yield encode_done()

    return StreamingResponse(event_stream(), headers=SSE_HEADERS)
