"""笔记路由:POST /api/notes(保存)、GET /api/notes(列表/搜索)、DELETE /api/notes/:id。

设计意图:
    对应原项目 lib/actions/notes.ts。用户从 AI 回答中划线保存笔记,
    或在 Library 面板浏览/搜索/删除。笔记可关联来源聊天与消息。

    认证: ENABLE_AUTH=false 时共享匿名用户;ENABLE_AUTH=true 时从 JWT 解析。
    分页用游标(updatedAt, id)而非 offset——笔记可能被编辑,offset 分页不稳定。
"""

import json
import uuid
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Depends, Header, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ryoshi.auth import AuthError, AuthUser, resolve_user
from ryoshi.db.engine import get_session
from ryoshi.db.models import Note

router = APIRouter(prefix="/api/notes", tags=["notes"])


async def _current_user(authorization: str | None = Header(None)) -> AuthUser:
    try:
        return await resolve_user(authorization, allow_anonymous_fallback=True)
    except AuthError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc


def _note_to_dict(note: Note) -> dict[str, Any]:
    return {
        "id": note.id,
        "title": note.title,
        "content": note.content,
        "chatId": note.chat_id,
        "sourceMessageId": note.source_message_id,
        "createdAt": note.created_at.isoformat() if note.created_at else None,
        "updatedAt": note.updated_at.isoformat() if note.updated_at else None,
    }


class SaveNoteRequest(BaseModel):
    content: str
    title: str | None = None
    chatId: str | None = None
    sourceMessageId: str | None = None


def _derive_title(content: str, title: str | None) -> str:
    """从内容推导标题:显式 title > 内容首行(截断) > 'Untitled note'。"""
    if title and title.strip():
        return title.strip()[:255]
    first_line = content.strip().split("\n")[0].strip()
    return (first_line[:80] + ("..." if len(first_line) > 80 else "")) or "Untitled note"


@router.post("", status_code=201)
async def save_note(
    req: SaveNoteRequest,
    session: AsyncSession = Depends(get_session),
    user: AuthUser = Depends(_current_user),
):
    """保存一条笔记。对应原项目 saveNote。"""
    trimmed = req.content.strip()
    if not trimmed:
        raise HTTPException(status_code=400, detail="Nothing to save.")

    note = Note(
        id=uuid.uuid4().hex[:24],
        user_id=user.id,
        chat_id=req.chatId,
        source_message_id=req.sourceMessageId,
        title=_derive_title(trimmed, req.title),
        content=trimmed,
    )
    session.add(note)
    await session.commit()
    return _note_to_dict(note)


@router.get("")
async def list_notes(
    limit: int = Query(20, ge=1, le=100),
    cursor: str | None = Query(None),
    query: str | None = Query(None),
    session: AsyncSession = Depends(get_session),
    user: AuthUser = Depends(_current_user),
):
    """分页/搜索笔记。对应原项目 listNotes / searchNotes(合并为一个端点)。

    游标格式: JSON {"updatedAt": "...", "id": "..."},按 (updated_at DESC, id DESC) 翻页。
    """
    stmt = select(Note).where(Note.user_id == user.id)

    # 搜索模式: 标题或内容包含关键词
    if query:
        from sqlalchemy import or_

        stmt = stmt.where(
            or_(
                Note.title.ilike(f"%{query}%"),
                Note.content.ilike(f"%{query}%"),
            )
        )

    # 游标分页
    if cursor:
        try:
            c = json.loads(cursor)
            cursor_time = datetime.fromisoformat(c["updatedAt"].replace("Z", "+00:00"))
            cursor_id = c["id"]
            stmt = stmt.where(
                (Note.updated_at < cursor_time)
                | ((Note.updated_at == cursor_time) & (Note.id < cursor_id))
            )
        except (json.JSONDecodeError, KeyError, ValueError):
            raise HTTPException(status_code=400, detail="Invalid cursor") from None

    stmt = stmt.order_by(Note.updated_at.desc(), Note.id.desc()).limit(limit + 1)
    result = await session.execute(stmt)
    notes = list(result.scalars().all())

    has_more = len(notes) > limit
    notes = notes[:limit]

    # nextCursor 直接返回对象:前端会自行 JSON.stringify 后放入下次请求的
    # cursor 参数;若这里先 json.dumps,前端再 stringify 一次就双重编码了。
    next_cursor = None
    if has_more and notes:
        last = notes[-1]
        next_cursor = {
            "updatedAt": last.updated_at.isoformat() if last.updated_at else "",
            "id": last.id,
        }

    return {
        "success": True,
        "notes": [_note_to_dict(n) for n in notes],
        "nextCursor": next_cursor,
        "hasMore": has_more,
    }


@router.delete("/{note_id}", status_code=204)
async def delete_note(
    note_id: str,
    session: AsyncSession = Depends(get_session),
    user: AuthUser = Depends(_current_user),
):
    """删除一条笔记。仅 owner 可操作。"""
    note = await session.get(Note, note_id)
    if note is None or note.user_id != user.id:
        raise HTTPException(status_code=404, detail="Note not found")
    await session.delete(note)
    await session.commit()
