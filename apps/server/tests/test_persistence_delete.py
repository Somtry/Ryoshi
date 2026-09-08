"""delete_message_and_after 的测试(regenerate 数据一致性)。

设计意图:
    前端 regenerate/编辑消息时,AI SDK 在本地截断消息列表;后端必须做
    同样的删除,否则旧回答留在库里、刷新后"复活"。这里用内存 SQLite
    跑真实的 persistence 代码,锁定删除语义:
      - assistant 目标:该回答及其后全部轮次被删,之前的保留
      - user 目标(编辑重发):该消息及其后被删
      - 跨会话/不存在的 id:不动任何数据
"""

from datetime import datetime, timedelta

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from ryoshi.db.models import Base, Chat, Message, Part
from ryoshi.db.persistence import delete_message_and_after, load_chat


@pytest.fixture
async def db():
    """内存 SQLite + 建表,产出 session factory。"""
    engine = create_async_engine("sqlite+aiosqlite://")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(bind=engine, expire_on_commit=False)
    yield factory
    await engine.dispose()


async def _seed_chat(factory, chat_id: str, user_id: str = "u1") -> list[str]:
    """造一场 4 条消息的会话:user1 → assistant1 → user2 → assistant2。"""
    base_time = datetime(2026, 9, 8, 12, 0, 0)
    async with factory() as session:
        session.add(Chat(id=chat_id, title="测试", user_id=user_id, visibility="private"))
        ids = []
        for i, role in enumerate(["user", "assistant", "user", "assistant"]):
            msg_id = f"msg-{chat_id}-{i + 1}"
            ids.append(msg_id)
            session.add(
                Message(
                    id=msg_id,
                    chat_id=chat_id,
                    role=role,
                    created_at=base_time + timedelta(minutes=i),  # 时间递增
                )
            )
            session.add(
                Part(message_id=msg_id, order=0, type="text", text_text=f"{role}-{i + 1}")
            )
        await session.commit()
    return ids


async def _remaining_ids(factory, chat_id: str) -> list[str]:
    async with factory() as session:
        # load_chat 的所有权校验:private 会话须以 owner 身份读
        chat = await load_chat(session, chat_id, user_id="u1")
        return [m["id"] for m in chat["messages"]]


async def test_删除assistant目标_该回答及其后全部删除_之前保留(db):
    ids = await _seed_chat(db, "c1")
    # regenerate 第 2 轮回答(msg-4 是最后一轮 assistant;这里测中间轮:
    # 删除 assistant1(msg-2)→ msg-2/3/4 全删,只剩 msg-1)
    async with db() as session:
        deleted = await delete_message_and_after(session, "c1", ids[1])
    assert deleted == 3
    assert await _remaining_ids(db, "c1") == [ids[0]]


async def test_删除最后一轮assistant_仅删该回答(db):
    ids = await _seed_chat(db, "c2")
    async with db() as session:
        deleted = await delete_message_and_after(session, "c2", ids[3])
    assert deleted == 1
    assert await _remaining_ids(db, "c2") == ids[:3]


async def test_删除user目标_编辑重发场景_该消息及其后删除(db):
    ids = await _seed_chat(db, "c3")
    # 编辑第 2 轮 user 消息(msg-3)重发 → msg-3/4 删除,前两轮保留
    async with db() as session:
        deleted = await delete_message_and_after(session, "c3", ids[2])
    assert deleted == 2
    assert await _remaining_ids(db, "c3") == ids[:2]


async def test_消息不属于该会话_不删任何东西(db):
    ids = await _seed_chat(db, "c4")
    async with db() as session:
        deleted = await delete_message_and_after(session, "other-chat", ids[1])
    assert deleted == 0
    assert await _remaining_ids(db, "c4") == ids  # 原封不动


async def test_不存在的消息id_不删任何东西(db):
    ids = await _seed_chat(db, "c5")
    async with db() as session:
        deleted = await delete_message_and_after(session, "c5", "no-such-msg")
    assert deleted == 0
    assert await _remaining_ids(db, "c5") == ids


async def test_同秒消息_一并纳入删除(db):
    """同一 created_at 的多条消息(同轮 user+assistant)不会留尾巴。"""
    async with db() as session:
        session.add(Chat(id="c6", title="同秒", user_id="u1", visibility="private"))
        same_time = datetime(2026, 9, 8, 12, 0, 0)
        # 第一轮(user1, t0) → 第二轮(user2/assistant2 同秒 t1)
        session.add(Message(id="m1", chat_id="c6", role="user", created_at=same_time))
        session.add(
            Message(id="m2", chat_id="c6", role="assistant", created_at=same_time + timedelta(minutes=1))
        )
        session.add(
            Message(id="m3", chat_id="c6", role="user", created_at=same_time + timedelta(minutes=1))
        )
        await session.commit()

    # 从 m2 开始删:m2 与同秒的 m3 都要删掉
    async with db() as session:
        deleted = await delete_message_and_after(session, "c6", "m2")
    assert deleted == 2
    assert await _remaining_ids(db, "c6") == ["m1"]
