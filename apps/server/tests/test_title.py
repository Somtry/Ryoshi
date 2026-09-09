"""LLM 会话标题生成的行为测试(mock 模型,不发真实请求)。"""

from unittest.mock import AsyncMock, patch

from langchain_core.messages import AIMessage

from ryoshi.agents.title import fallback_title, generate_chat_title


class TestGenerateChatTitle:
    async def test_成功生成_剥引号截断(self):
        fake_model = AsyncMock()
        fake_model.ainvoke.return_value = AIMessage(content='"Rust 与 Go 的对比"')
        with patch("ryoshi.agents.models.aget_model", return_value=fake_model):
            title = await generate_chat_title("帮我详细对比一下 Rust 和 Go 的并发模型与内存安全", "openai:gpt-4o", None)
        assert title == "Rust 与 Go 的对比"
        fake_model.ainvoke.assert_awaited_once()

    async def test_模型失败_返回截断兜底(self):
        with patch("ryoshi.agents.models.aget_model", side_effect=RuntimeError("no key")):
            title = await generate_chat_title("一个很长很长很长的问题" * 10, "openai:gpt-4o", None)
        assert title.startswith("一个很长")
        assert len(title) <= 75

    async def test_空消息_兜底NewChat(self):
        with patch("ryoshi.agents.models.aget_model", side_effect=RuntimeError("x")):
            assert await generate_chat_title("", "openai:gpt-4o", None) == "New Chat"


class TestFallbackTitle:
    def test_截断75字符(self):
        assert fallback_title("x" * 200) == "x" * 75
        assert fallback_title("") == "New Chat"
