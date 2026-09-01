"""聊天消息持久化:UIMessage ↔ 数据库 的映射与 CRUD。

设计意图:
    对应原项目 lib/utils/message-mapping.ts + lib/actions/chat.ts。
    原项目把"前端 UIMessage 的 parts"摊平成 parts 宽列表(一类部件一组列),
    这里用同样的映射规则,只是从 Drizzle 换成 SQLAlchemy 2.0 异步会话。

    职责分两层:
      - 纯函数映射: ui_parts_to_db_parts / build_ui_message(无 I/O,可单测)
      - 会话操作:   create_chat_with_first_message / upsert_message / load_chat
                   (带 AsyncSession,直接落库)

    关键约束(与原项目一致):
      - parts.order 记录部件在消息内的先后,流式渲染依赖它
      - tool 部件的 state 决定渲染态(input-available / output-available / output-error)
      - upsert 语义:同 id 消息已存在则先删旧 parts 再重建(覆盖式)
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from ryoshi.db.models import Chat, Message, Part

DEFAULT_CHAT_TITLE = "Untitled"


def generate_id() -> str:
    """生成消息/会话 id。与原项目 generateId 同形(无分隔符的十六进制)。"""
    return uuid.uuid4().hex


# ---- 工具名归一化:tool-call 里的原始名 ↔ parts 表的列名前缀 ----
# 原项目 toolName 与列名不一致(如 askQuestion → question 列),这里做双向映射。
_TOOL_TO_COLUMN = {
    "search": "search",
    "fetch": "fetch",
    "askQuestion": "question",
    "question": "question",
    "todoWrite": "todoWrite",
    "todoRead": "todoRead",
}
_COLUMN_TO_TOOL = {v: k for k, v in _TOOL_TO_COLUMN.items()}
# question 列在读取时统一映射回 askQuestion(与原项目 getOriginalToolName 一致)
_COLUMN_TO_TOOL["question"] = "askQuestion"


def _tool_to_column(tool_name: str) -> str:
    """把工具名映射到 parts 表列前缀。动态工具(MCP 等)归为 dynamic。"""
    if tool_name.startswith("mcp__") or tool_name.startswith("dynamic__"):
        return "dynamic"
    return _TOOL_TO_COLUMN.get(tool_name, tool_name)


def _extract_text(parts: list[dict[str, Any]]) -> str:
    """从 parts 里拼出纯文本(用于从首条用户消息生成会话标题)。"""
    return "".join(p.get("text", "") for p in parts if p.get("type") == "text").strip()


def ui_parts_to_db_parts(parts: list[dict[str, Any]], message_id: str) -> list[Part]:
    """把前端 UIMessage 的 parts 数组摊平成 parts 宽列行(不落库)。

    与原项目 mapUIMessagePartsToDBParts 逐条对应:
      - text / reasoning / file / source-url / source-document 各有专属列
      - tool-call → type=tool-<name>,只写 input 列(state=input-available)
      - tool-result → type=tool-<name>,写 output 列(state=output-available)
      - data-* → data_prefix + data_content 通用列
    """
    rows: list[Part] = []
    for index, part in enumerate(parts):
        ptype = part.get("type", "")
        base: dict[str, Any] = {"message_id": message_id, "order": index, "type": ptype}

        if ptype == "text":
            rows.append(Part(**base, text_text=part.get("text", "")))
        elif ptype == "reasoning":
            rows.append(
                Part(
                    **base,
                    reasoning_text=part.get("text", ""),
                    provider_metadata=part.get("providerMetadata"),
                )
            )
        elif ptype == "file":
            rows.append(
                Part(
                    **base,
                    file_media_type=part.get("mediaType", ""),
                    file_filename=part.get("filename", ""),
                    # 有 key(已上传 S3)就不存临时 url,与原项目一致
                    file_url=None if part.get("key") else part.get("url"),
                    file_key=part.get("key"),
                )
            )
        elif ptype == "source-url":
            rows.append(
                Part(
                    **base,
                    source_url_source_id=part.get("sourceId", ""),
                    source_url_url=part.get("url", ""),
                    source_url_title=part.get("title", ""),
                )
            )
        elif ptype == "source-document":
            rows.append(
                Part(
                    **base,
                    source_document_source_id=part.get("sourceId", ""),
                    source_document_media_type=part.get("mediaType", ""),
                    source_document_title=part.get("title", ""),
                    source_document_filename=part.get("filename", ""),
                    source_document_url=part.get("url", ""),
                    source_document_snippet=part.get("snippet", ""),
                )
            )
        elif ptype.startswith("tool-"):
            # 工具部件:state 决定写 input 还是 output 列
            tool_name = ptype[5:]  # 去掉 'tool-' 前缀
            column = _tool_to_column(tool_name)
            state = part.get("state", "input-available")
            row = Part(
                **base,
                tool_tool_call_id=part.get("toolCallId") or generate_id(),
                tool_state=state,
                tool_error_text=part.get("errorText"),
            )
            if part.get("input") is not None:
                setattr(row, f"tool_{column}_input", part["input"])
            if part.get("output") is not None:
                setattr(row, f"tool_{column}_output", part["output"])
            rows.append(row)
        elif ptype == "step-start":
            rows.append(Part(**base))  # 仅占位,无附加列
        elif ptype.startswith("data-"):
            rows.append(
                Part(
                    **base,
                    data_prefix=ptype[5:],
                    data_content=part.get("data", part),
                    data_id=part.get("id"),
                )
            )
        # 其余类型(step-finish 等)不持久化,跳过

    # 重新编号 order(过滤掉未持久化的类型后保持连续)
    for i, row in enumerate(rows):
        row.order = i
    return rows


def db_parts_to_ui_parts(rows: list[Part]) -> list[dict[str, Any]]:
    """把 parts 宽列行还原成前端 UIMessage 的 parts 数组。

    与原项目 mapDBPartToUIMessagePart 对应;按 order 排序由查询保证。
    """
    parts: list[dict[str, Any]] = []
    for row in rows:
        t = row.type
        if t == "text":
            parts.append({"type": "text", "text": row.text_text or ""})
        elif t == "reasoning":
            parts.append(
                {
                    "type": "reasoning",
                    "text": row.reasoning_text or "",
                    **({"providerMetadata": row.provider_metadata} if row.provider_metadata else {}),
                }
            )
        elif t == "file":
            parts.append(
                {
                    "type": "file",
                    "mediaType": row.file_media_type or "",
                    "filename": row.file_filename or "",
                    "url": "" if row.file_key else (row.file_url or ""),
                    **({"key": row.file_key} if row.file_key else {}),
                }
            )
        elif t == "source-url":
            parts.append(
                {
                    "type": "source-url",
                    "sourceId": row.source_url_source_id or "",
                    "url": row.source_url_url or "",
                    "title": row.source_url_title or "",
                }
            )
        elif t == "source-document":
            parts.append(
                {
                    "type": "source-document",
                    "sourceId": row.source_document_source_id or "",
                    "mediaType": row.source_document_media_type or "",
                    "title": row.source_document_title or "",
                    "filename": row.source_document_filename or "",
                    "url": row.source_document_url or "",
                    "snippet": row.source_document_snippet or "",
                }
            )
        elif t.startswith("tool-"):
            column = t[5:]
            tool_name = _COLUMN_TO_TOOL.get(column, column)
            part: dict[str, Any] = {
                "type": f"tool-{tool_name}",
                "toolCallId": row.tool_tool_call_id or "",
                "state": row.tool_state or "input-available",
            }
            inp = getattr(row, f"tool_{column}_input", None)
            out = getattr(row, f"tool_{column}_output", None)
            if inp is not None:
                part["input"] = inp
            if out is not None:
                part["output"] = out
            if row.tool_error_text:
                part["errorText"] = row.tool_error_text
            parts.append(part)
        elif t == "step-start":
            parts.append({"type": "step-start"})
        elif row.data_prefix:
            parts.append(
                {
                    "type": f"data-{row.data_prefix}",
                    "data": row.data_content,
                    **({"id": row.data_id} if row.data_id else {}),
                }
            )
    return parts


# ---- 会话级 CRUD(带 I/O)----


async def create_chat_with_first_message(
    session: AsyncSession,
    chat_id: str,
    user_message: dict[str, Any],
    user_id: str,
    title: str | None = None,
) -> Chat:
    """新建会话并保存首条用户消息(单事务)。

    对应原项目 createChatWithFirstMessage。标题从首条消息文本截取。
    """
    chat_title = (title or _extract_text(user_message.get("parts", [])) or DEFAULT_CHAT_TITLE)[:255]
    chat = Chat(id=chat_id, title=chat_title, user_id=user_id, visibility="private")
    session.add(chat)

    msg = Message(
        id=user_message.get("id") or generate_id(),
        chat_id=chat_id,
        role="user",
        extra_metadata=user_message.get("metadata"),
    )
    session.add(msg)
    for part_row in ui_parts_to_db_parts(user_message.get("parts", []), msg.id):
        session.add(part_row)

    await session.commit()
    return chat


async def upsert_message(
    session: AsyncSession,
    chat_id: str,
    message: dict[str, Any],
) -> Message:
    """写入一条消息(存在则覆盖 parts)。对应原项目 upsertMessage。

    AI 回答在流式结束后落库;若同一 message.id 已有记录(如重试),
    先删旧 parts 再按最新内容重建,保证与最终流式结果一致。
    """
    message_id = message.get("id") or generate_id()

    existing = await session.get(Message, message_id)
    if existing is not None:
        # 覆盖式:清掉旧 parts,重建
        await session.execute(delete(Part).where(Part.message_id == message_id))
        existing.role = message.get("role", existing.role)
        existing.extra_metadata = message.get("metadata")
        db_message = existing
    else:
        db_message = Message(
            id=message_id,
            chat_id=chat_id,
            role=message.get("role", "assistant"),
            extra_metadata=message.get("metadata"),
        )
        session.add(db_message)

    for part_row in ui_parts_to_db_parts(message.get("parts", []), message_id):
        session.add(part_row)

    await session.commit()
    return db_message


async def load_chat(
    session: AsyncSession, chat_id: str, user_id: str | None = None
) -> dict[str, Any] | None:
    """按 id 加载一场聊天(含全部消息的 parts)。

    返回结构对齐前端 loadChat 期望:{messages, title, visibility}。
    messages 按创建时间排序,每条的 parts 按 order 排序。

    所有权校验(对应原项目 loadChatWithMessages):
    visibility='private' 的会话仅 owner 可读;visibility='public'(已分享)
    的会话任何人可读。user_id 为 None 时视为匿名访客,仅能读 public。
    """
    # 先取消息(按时间),再按 message_id 批量取 parts(按 order),避免 N+1
    result = await session.execute(
        select(Message).where(Message.chat_id == chat_id).order_by(Message.created_at)
    )
    messages = list(result.scalars().all())
    if not messages:
        # 可能是只有会话没有消息的边界;仍返回空历史
        chat = await session.get(Chat, chat_id)
        if chat is None:
            return None
        if chat.visibility == "private" and chat.user_id != user_id:
            return None
        return {"messages": [], "title": chat.title, "visibility": chat.visibility}

    # 有消息时再校验所有权
    chat = await session.get(Chat, chat_id)
    if chat is not None and chat.visibility == "private" and chat.user_id != user_id:
        return None

    msg_ids = [m.id for m in messages]
    parts_result = await session.execute(
        select(Part).where(Part.message_id.in_(msg_ids)).order_by(Part.order)
    )
    parts_by_msg: dict[str, list[Part]] = {}
    for p in parts_result.scalars().all():
        parts_by_msg.setdefault(p.message_id, []).append(p)

    ui_messages = [
        {
            "id": m.id,
            "role": m.role,
            "parts": db_parts_to_ui_parts(parts_by_msg.get(m.id, [])),
            **({"metadata": m.extra_metadata} if m.extra_metadata else {}),
        }
        for m in messages
    ]

    return {
        "messages": ui_messages,
        "title": chat.title if chat else DEFAULT_CHAT_TITLE,
        "visibility": chat.visibility if chat else "private",
    }


async def get_chats_page(
    session: AsyncSession, user_id: str, limit: int = 20, offset: int = 0
) -> dict[str, Any]:
    """分页拉取某用户的会话列表(新的在前)。对应原项目 getChatsPage。"""
    result = await session.execute(
        select(Chat)
        .where(Chat.user_id == user_id)
        .order_by(Chat.created_at.desc())
        .limit(limit + 1)  # 多取一条判断是否有下一页
        .offset(offset)
    )
    chats = list(result.scalars().all())
    has_more = len(chats) > limit
    chats = chats[:limit]
    return {
        "chats": [
            {
                "id": c.id,
                "title": c.title,
                "createdAt": c.created_at.isoformat() if c.created_at else None,
                "visibility": c.visibility,
            }
            for c in chats
        ],
        "nextOffset": offset + limit if has_more else None,
    }


async def update_chat_visibility(
    session: AsyncSession, chat_id: str, user_id: str, visibility: str
) -> bool:
    """把会话可见性设为 public/private。对应原项目 updateChatVisibility。

    仅 owner 可修改;非 owner 返回 False。
    """
    chat = await session.get(Chat, chat_id)
    if chat is None or chat.user_id != user_id:
        return False
    chat.visibility = visibility
    await session.commit()
    return True


async def delete_chat(session: AsyncSession, chat_id: str, user_id: str) -> bool:
    """删除一场聊天(级联删除消息与 parts)。对应原项目 deleteChat。

    仅 owner 可删除;非 owner 返回 False。
    SQLAlchemy 的 session.delete() 不会自动级联到未加载的 ORM 对象,
    需要显式按 FK 顺序删: parts → messages → chat。
    """
    chat = await session.get(Chat, chat_id)
    if chat is None or chat.user_id != user_id:
        return False

    # 显式级联删除(FK 有 ondelete=CASCADE,但 ORM 层面需要显式删)
    msg_ids_result = await session.execute(
        select(Message.id).where(Message.chat_id == chat_id)
    )
    msg_ids = [row[0] for row in msg_ids_result.all()]
    if msg_ids:
        await session.execute(delete(Part).where(Part.message_id.in_(msg_ids)))
        await session.execute(delete(Message).where(Message.chat_id == chat_id))
    await session.delete(chat)
    await session.commit()
    return True


async def clear_chats(session: AsyncSession, user_id: str) -> int:
    """清空某用户的全部聊天。对应原项目 clearChats。返回删除条数。"""
    result = await session.execute(select(Chat.id).where(Chat.user_id == user_id))
    chat_ids = [row[0] for row in result.all()]
    if not chat_ids:
        return 0

    # 批量级联: parts → messages → chats
    msg_ids_result = await session.execute(
        select(Message.id).where(Message.chat_id.in_(chat_ids))
    )
    msg_ids = [row[0] for row in msg_ids_result.all()]
    if msg_ids:
        await session.execute(delete(Part).where(Part.message_id.in_(msg_ids)))
    await session.execute(delete(Message).where(Message.chat_id.in_(chat_ids)))
    await session.execute(delete(Chat).where(Chat.user_id == user_id))
    await session.commit()
    return len(chat_ids)
