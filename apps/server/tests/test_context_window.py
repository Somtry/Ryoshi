"""上下文窗口查表:前缀匹配与默认值。"""

from ryoshi.chat.context_window import _lookup_window, get_max_allowed_tokens


class TestLookupWindow:
    def test_精确命中(self):
        assert _lookup_window("gpt-4o")["contextWindow"] == 128000

    def test_前缀命中_BYOK自定义id(self):
        # BYOK 用户手填的新模型 id 没登记,但前缀能对上量级
        assert _lookup_window("gpt-5.2-mini")["contextWindow"] == 400000
        assert _lookup_window("claude-sonnet-4-6-20260101")["contextWindow"] == 200000
        assert _lookup_window("deepseek-reasoner")["contextWindow"] == 128000
        assert _lookup_window("gemini-3.0-pro")["contextWindow"] == 1048576

    def test_最长前缀优先(self):
        # gpt-4o-mini-2024 精确没登记,但 "gpt-4o" 比 "gpt-" 更长更具体
        # (表里没有裸 "gpt-",用 gpt-4o 与 gpt-4.1 验证前缀竞争)
        assert _lookup_window("gpt-4.1-mini")["contextWindow"] == 1047576

    def test_完全未知_默认128k(self):
        assert _lookup_window("some-unknown-model")["contextWindow"] == 128000

    def test_截断预算计算(self):
        # 128k - 8k 输出 - 10% 缓冲 = ~107k
        budget = get_max_allowed_tokens("some-unknown-model")
        assert 100000 < budget <= 128000
