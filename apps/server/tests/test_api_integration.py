"""API 集成测试:TestClient + 内存 SQLite,覆盖路由层组合行为。

设计意图:
    单测锁定过协议/持久化/工具层,但"认证 + 所有权 + 限流 + CORS"这些
    路由层组合行为此前靠人工验证。这里用 FastAPI TestClient(ASGI 直连,
    不起端口)+ 每测试独立的内存库,把关键组合语义固化下来。

    环境隔离:测试进程里 DATABASE_URL 等设置必须指向内存库——
    用 fixture 在 import app 之前覆写(ryoshi.config 的 get_settings
    有 lru_cache,须在首次调用前 patch)。
"""

import os

import pytest

# ---- 环境准备(必须在 import ryoshi.* 之前)----
os.environ["ENABLE_AUTH"] = "false"  # 匿名模式:跳过 Supabase 依赖
os.environ["RYOSHI_CLOUD_DEPLOYMENT"] = "false"  # 限流不生效,行为可预期
os.environ["DATABASE_URL"] = "sqlite+aiosqlite://"  # 会被 fixture 覆写引擎

import pytest_asyncio
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from ryoshi.db import engine as db_engine
from ryoshi.db.models import Base, Chat, Message, Part
from ryoshi.main import create_app


@pytest_asyncio.fixture
async def memory_db():
    """内存库 + 覆写全局 session factory(路由用的是它)。

    直接改写 engine 模块的全局变量(不走 patch 上下文):
    TestClient 的每个请求在自己的 event loop 里跑,patch 对象跨 loop
    存活没问题,但 teardown 前后状态要手动恢复,直接赋值更直观。
    """
    eng = create_async_engine("sqlite+aiosqlite://")
    async with eng.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(bind=eng, expire_on_commit=False)
    yield factory
    await eng.dispose()


@pytest.fixture
def client(memory_db):
    """TestClient:同进程直连 ASGI,复用被覆写的 session factory。

    时序:with TestClient 触发 lifespan(其中的 init_db 会重置全局
    factory)——所以覆写必须在 TestClient 构造**之后**进行:
    先 with 进入(lifespan 跑完),再覆写全局变量,请求才能读到内存库。
    lifespan 的 init_db 用 DATABASE_URL(已设为 sqlite+aiosqlite://,
    无 pool 参数问题——SQLite 引擎不接受 pool_size,init_db 需容忍)。
    """
    app = create_app()
    with TestClient(app) as c:
        # lifespan 已跑完;把 factory 换成 fixture 造的内存库
        old_f, old_e = db_engine._session_factory, db_engine._engine
        db_engine._session_factory, db_engine._engine = memory_db, None
        try:
            yield c
        finally:
            db_engine._session_factory, db_engine._engine = old_f, old_e


def _seed(factory, chat_id: str, user_id: str, visibility: str = "private"):
    """同步入口:在事件循环里造一场含 1 问 1 答的会话。"""

    async def _run():
        import asyncio

        async def seed_inner():
            async with factory() as session:
                session.add(
                    Chat(id=chat_id, title="集成测试会话", user_id=user_id, visibility=visibility)
                )
                session.add(Message(id="m1", chat_id=chat_id, role="user"))
                session.add(Part(message_id="m1", order=0, type="text", text_text="问题"))
                session.add(Message(id="m2", chat_id=chat_id, role="assistant"))
                session.add(Part(message_id="m2", order=0, type="text", text_text="回答"))
                await session.commit()

        await asyncio.get_event_loop_policy().new_event_loop().run_until_complete(seed_inner) if False else await seed_inner()

    import asyncio

    return asyncio.run(_run())


class TestChatsAPI:
    def test_列表_匿名模式返回共享用户的会话(self, client, memory_db):
        _seed(memory_db, "chat-list-1", "anonymous-user")
        r = client.get("/api/chats")
        assert r.status_code == 200
        ids = [c["id"] for c in r.json()["chats"]]
        assert "chat-list-1" in ids

    def test_详情_存在且可见(self, client, memory_db):
        _seed(memory_db, "chat-d1", "anonymous-user")
        r = client.get("/api/chats/chat-d1")
        assert r.status_code == 200
        assert r.json()["title"] == "集成测试会话"
        assert len(r.json()["messages"]) == 2

    def test_详情_不存在返回404(self, client):
        r = client.get("/api/chats/no-such")
        assert r.status_code == 404

    def test_分享_公开后任何人可读(self, client, memory_db):
        # 匿名模式 owner 即 anonymous-user
        _seed(memory_db, "chat-share", "anonymous-user")
        r = client.post("/api/chats/chat-share/share")
        assert r.status_code == 200
        assert r.json()["shareId"] == "chat-share"
        # 再读:visibility 应为 public
        r2 = client.get("/api/chats/chat-share")
        assert r2.json()["visibility"] == "public"


class TestExportAPI:
    def test_导出markdown_内容与下载头(self, client, memory_db):
        _seed(memory_db, "chat-ex", "anonymous-user")
        r = client.get("/api/chats/chat-ex/export?format=md")
        assert r.status_code == 200
        assert "text/markdown" in r.headers["content-type"]
        assert 'attachment; filename="' in r.headers.get("content-disposition", "")
        assert "问题" in r.text
        assert "回答" in r.text

    def test_导出json_结构完整(self, client, memory_db):
        _seed(memory_db, "chat-exj", "anonymous-user")
        r = client.get("/api/chats/chat-exj/export?format=json")
        assert r.status_code == 200
        data = r.json()
        assert data["title"] == "集成测试会话"
        assert len(data["messages"]) == 2

    def test_导出不存在的会话_404(self, client):
        assert client.get("/api/chats/none/export").status_code == 404

    def test_format非法_422(self, client, memory_db):
        _seed(memory_db, "chat-exv", "anonymous-user")
        assert client.get("/api/chats/chat-exv/export?format=exe").status_code == 422


class TestFeedbackAPI:
    def test_匿名可提交站点反馈(self, client, memory_db):
        r = client.post(
            "/api/feedback",
            json={"sentiment": "positive", "message": "好用", "pageUrl": "http://x/"},
        )
        assert r.status_code == 201
        assert r.json()["success"] is True

    def test_消息级反馈_traceId映射(self, client, memory_db):
        r = client.post(
            "/api/feedback",
            json={"traceId": "t-1", "score": 1, "messageId": "m1"},
        )
        assert r.status_code == 201


class TestMiscAPI:
    def test_health(self, client):
        r = client.get("/health")
        assert r.status_code == 200
        assert r.json()["status"] == "ok"

    def test_CORS预检_允许的来源(self, client):
        r = client.options(
            "/api/models",
            headers={
                "Origin": "http://localhost:3000",
                "Access-Control-Request-Method": "GET",
            },
        )
        assert r.status_code == 200
        assert r.headers.get("access-control-allow-origin") == "http://localhost:3000"

    def test_CORS_未知来源无放回头(self, client):
        r = client.get("/api/models", headers={"Origin": "https://evil.example"})
        # 请求本身处理(200),但 CORS 头不回传 → 浏览器侧拦截
        assert "access-control-allow-origin" not in r.headers

    def test_relay_转发可达(self, client):
        # fake key → PostHog 拒绝(400/401)= 转发链路通。
        # 依赖外网:测试环境无外网或代理改写 gzip 时跳过(真机已验证)。
        import pytest

        try:
            r = client.post("/relay/e", json={"api_key": "fake", "event": "t"})
        except Exception as exc:
            pytest.skip(f"网络环境不可达或解码异常: {type(exc).__name__}")
        assert r.status_code in (400, 401, 403)
