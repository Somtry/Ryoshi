"""文件库路由:GET /api/files(列表/搜索)、DELETE /api/files/:id。

设计意图:
    对应原项目 lib/actions/files.ts。用户在 Library 面板浏览/搜索/删除
    已上传的文件。文件元信息存在 files 表,实际内容在对象存储(S3/R2)。

    认证: ENABLE_AUTH=false 时共享匿名用户;ENABLE_AUTH=true 时从 JWT 解析。
    分页用游标(updatedAt, id),与笔记路由保持一致。
"""

import json
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, Header, HTTPException, Query
from sqlalchemy import delete as sa_delete
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from ryoshi.auth import AuthError, AuthUser, resolve_user
from ryoshi.db.engine import get_session
from ryoshi.db.models import LibraryFile

router = APIRouter(prefix="/api/files", tags=["files"])


async def _current_user(authorization: str | None = Header(None)) -> AuthUser:
    try:
        return await resolve_user(authorization, allow_anonymous_fallback=True)
    except AuthError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc


def _file_to_dict(f: LibraryFile) -> dict[str, Any]:
    return {
        "id": f.id,
        "filename": f.filename,
        "objectKey": f.object_key,
        "mediaType": f.media_type,
        "size": f.size,
        "chatId": f.chat_id,
        "createdAt": f.created_at.isoformat() if f.created_at else None,
        "updatedAt": f.updated_at.isoformat() if f.updated_at else None,
        # LibraryFileItem 需要的 key/url 字段
        "key": f.object_key,
    }


@router.get("")
async def list_files(
    limit: int = Query(20, ge=1, le=100),
    cursor: str | None = Query(None),
    query: str | None = Query(None),
    session: AsyncSession = Depends(get_session),
    user: AuthUser = Depends(_current_user),
):
    """分页/搜索文件库。对应原项目 listFiles / searchFiles。"""
    stmt = select(LibraryFile).where(LibraryFile.user_id == user.id)

    if query:
        stmt = stmt.where(
            or_(
                LibraryFile.filename.ilike(f"%{query}%"),
                LibraryFile.media_type.ilike(f"%{query}%"),
            )
        )

    if cursor:
        try:
            c = json.loads(cursor)
            cursor_time = datetime.fromisoformat(c["updatedAt"].replace("Z", "+00:00"))
            cursor_id = c["id"]
            stmt = stmt.where(
                (LibraryFile.updated_at < cursor_time)
                | ((LibraryFile.updated_at == cursor_time) & (LibraryFile.id < cursor_id))
            )
        except (json.JSONDecodeError, KeyError, ValueError):
            raise HTTPException(status_code=400, detail="Invalid cursor") from None

    stmt = stmt.order_by(LibraryFile.updated_at.desc(), LibraryFile.id.desc()).limit(limit + 1)
    result = await session.execute(stmt)
    files = list(result.scalars().all())

    has_more = len(files) > limit
    files = files[:limit]

    next_cursor = None
    if has_more and files:
        last = files[-1]
        next_cursor = {
            "updatedAt": last.updated_at.isoformat() if last.updated_at else "",
            "id": last.id,
        }

    return {
        "success": True,
        "files": [_file_to_dict(f) for f in files],
        "nextCursor": next_cursor,
        "hasMore": has_more,
    }


@router.delete("/{file_id}", status_code=204)
async def delete_file(
    file_id: str,
    session: AsyncSession = Depends(get_session),
    user: AuthUser = Depends(_current_user),
):
    """删除一条文件记录。仅 owner 可操作。注意:只删 DB 记录,不删对象存储里的文件。"""
    file = await session.get(LibraryFile, file_id)
    if file is None or file.user_id != user.id:
        raise HTTPException(status_code=404, detail="File not found")
    await session.execute(sa_delete(LibraryFile).where(LibraryFile.id == file_id))
    await session.commit()
