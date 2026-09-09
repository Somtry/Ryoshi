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
from fastapi.responses import Response
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


async def _current_user(authorization: str | None = Header(None)) -> AuthUser:
    """FastAPI 依赖:从 Authorization header 解析当前用户。

    对应原项目 getCurrentUserId——ENABLE_AUTH=false 时返回匿名用户,
    ENABLE_AUTH=true 时校验 JWT。认证失败返回 401。
    """
    try:
        return await resolve_user(authorization, allow_anonymous_fallback=True)
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


@router.get("/{chat_id}/export")
async def export_chat(
    chat_id: str,
    format: str = Query("md", pattern="^(md|json)$"),
    session: AsyncSession = Depends(get_session),
    user: AuthUser = Depends(_current_user),
):
    """导出一场聊天为 Markdown 或 JSON(下载文件)。

    对应 P3-8:纯后端拼装(load_chat 已有完整 parts 数据),
    Content-Disposition 触发浏览器下载。Markdown 只保留
    user/assistant 的文本与图片引用(工具调用细节属调试信息);
    JSON 则全量(含 parts 元数据)供导入/分析。
    """
    chat = await load_chat(session, chat_id, user_id=user.id)
    if chat is None:
        raise HTTPException(status_code=404, detail="Chat not found")

    # 文件名里的标题:去路径分隔符防注入,限长
    safe_title = "".join(c for c in chat["title"] if c not in "/\\:*?\"<>|")[:50] or "chat"

    if format == "json":
        import json

        payload = json.dumps(
            {
                "title": chat["title"],
                "visibility": chat["visibility"],
                "messages": chat["messages"],
            },
            ensure_ascii=False,
            indent=2,
        )
        return Response(
            content=payload,
            media_type="application/json",
            headers={
                "Content-Disposition": f'attachment; filename="{safe_title}.json"',
            },
        )

    # ---- Markdown ----
    lines: list[str] = [f"# {chat['title']}", "", "---", ""]
    for m in chat["messages"]:
        role = "🧑 用户" if m["role"] == "user" else "🤖 Ryoshi"
        lines.append(f"### {role}")
        lines.append("")
        for p in m.get("parts", []):
            if p.get("type") == "text" and p.get("text"):
                lines.append(p["text"])
                lines.append("")
            elif p.get("type") == "file" and p.get("url"):
                lines.append(f"![{p.get('filename', '附件')}]({p['url']})")
                lines.append("")
            elif p.get("type") == "source-url" and p.get("url"):
                lines.append(f"- 来源: [{p.get('title') or p['url']}]({p['url']})")
        lines.append("")
    return Response(
        content="\n".join(lines),
        media_type="text/markdown; charset=utf-8",
        headers={
            "Content-Disposition": f'attachment; filename="{safe_title}.md"',
        },
    )
