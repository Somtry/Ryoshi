"""聊天历史路由:GET /api/chats(列表)、GET /api/chats/:id(含消息)。

设计意图:
    对应原项目 app/api/chats/route.ts 与 loadChat。
    前端侧栏(chat-history-client)轮询 /api/chats 拉历史列表;
    打开已有聊天(/search/:id)时调 /api/chats/:id 拿完整消息。

    认证:通过 Authorization: Bearer <supabase-jwt> 识别用户;
    ENABLE_AUTH=false(本地单人)时所有请求共享 ANONYMOUS_USER_ID,
    与原项目 getCurrentUserId 的匿名模式对齐。
"""

from fastapi import APIRouter, Depends, Header, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from ryoshi.auth import AuthError, AuthUser, resolve_user
from ryoshi.db.engine import get_session
from ryoshi.db.persistence import (
    clear_chats,
    delete_chat,
    get_chats_page,
    load_chat,
    update_chat_visibility,
)

router = APIRouter(prefix="/api/chats", tags=["chats"])


def _current_user(authorization: str | None = Header(None)) -> AuthUser:
    """FastAPI 依赖:从 Authorization header 解析当前用户。

    对应原项目 getCurrentUserId——ENABLE_AUTH=false 时返回匿名用户,
    ENABLE_AUTH=true 时校验 JWT。认证失败返回 401。
    """
    try:
        return resolve_user(authorization, allow_anonymous_fallback=True)
    except AuthError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc


@router.get("")
async def list_chats(
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    session: AsyncSession = Depends(get_session),
    user: AuthUser = Depends(_current_user),
):
    """分页拉取当前用户的会话列表(新的在前)。"""
    return await get_chats_page(session, user_id=user.id, limit=limit, offset=offset)


@router.get("/{chat_id}")
async def get_chat(
    chat_id: str,
    session: AsyncSession = Depends(get_session),
    user: AuthUser = Depends(_current_user),
):
    """加载一场聊天的完整消息历史。不存在返回 404,前端按 null 处理。"""
    chat = await load_chat(session, chat_id, user_id=user.id)
    if chat is None:
        raise HTTPException(status_code=404, detail="Chat not found")
    return chat


@router.post("/{chat_id}/share")
async def share_chat(
    chat_id: str,
    session: AsyncSession = Depends(get_session),
    user: AuthUser = Depends(_current_user),
):
    """把会话设为公开,返回可分享的 id。对应原项目 shareChat。

    仅 owner 可分享;非 owner 或会话不存在返回 404(不泄露存在性)。
    """
    ok = await update_chat_visibility(session, chat_id, user.id, "public")
    if not ok:
        raise HTTPException(status_code=404, detail="Chat not found")
    return {"shareId": chat_id}


@router.delete("/{chat_id}", status_code=204)
async def delete_chat_route(
    chat_id: str,
    session: AsyncSession = Depends(get_session),
    user: AuthUser = Depends(_current_user),
):
    """删除一场聊天(级联删除消息与 parts)。仅 owner 可操作。"""
    ok = await delete_chat(session, chat_id, user.id)
    if not ok:
        raise HTTPException(status_code=404, detail="Chat not found")


@router.delete("", status_code=204)
async def clear_all_chats(
    session: AsyncSession = Depends(get_session),
    user: AuthUser = Depends(_current_user),
):
    """清空当前用户的全部聊天。对应原项目 clearChats。"""
    await clear_chats(session, user.id)
