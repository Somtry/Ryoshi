"""聊天历史路由:GET /api/chats(列表)、GET /api/chats/:id(含消息)。

设计意图:
    对应原项目 app/api/chats/route.ts 与 loadChat。
    前端侧栏(chat-history-client)轮询 /api/chats 拉历史列表;
    打开已有聊天(/search/:id)时调 /api/chats/:id 拿完整消息。

    认证:阶段 4 仍是匿名模式(ENABLE_AUTH=false),所有请求共享
    ANONYMOUS_USER_ID。接入真实认证后,user_id 从 JWT 解析而来。
"""

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from ryoshi.config import get_settings
from ryoshi.db.engine import get_session
from ryoshi.db.persistence import get_chats_page, load_chat

router = APIRouter(prefix="/api/chats", tags=["chats"])


def _current_user_id() -> str:
    """取当前用户 id。匿名模式下返回配置的匿名用户。"""
    return get_settings().anonymous_user_id


@router.get("")
async def list_chats(
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    session: AsyncSession = Depends(get_session),
):
    """分页拉取当前用户的会话列表(新的在前)。"""
    return await get_chats_page(session, user_id=_current_user_id(), limit=limit, offset=offset)


@router.get("/{chat_id}")
async def get_chat(chat_id: str, session: AsyncSession = Depends(get_session)):
    """加载一场聊天的完整消息历史。不存在返回 404,前端按 null 处理。"""
    chat = await load_chat(session, chat_id)
    if chat is None:
        raise HTTPException(status_code=404, detail="Chat not found")
    return chat
