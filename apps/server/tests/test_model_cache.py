"""模型实例缓存:命中/换key失效/容量淘汰。"""

from ryoshi.agents.models import (
    _MODEL_CACHE,
    _cache_get,
    _cache_key,
    _cache_put,
)


class FakeModel:
    """够不上真 ChatModel,但缓存层只存取不校验类型。"""


class TestModelCache:
    def setup_method(self):
        _MODEL_CACHE.clear()

    def test_存取roundtrip(self):
        k = _cache_key("openai", "gpt-4o", "u1", "sk-abc")
        _cache_put(k, FakeModel())
        assert _cache_get(k) is not None

    def test_换key指纹_不命中(self):
        _cache_put(_cache_key("openai", "gpt-4o", "u1", "sk-old"), FakeModel())
        assert _cache_get(_cache_key("openai", "gpt-4o", "u1", "sk-new")) is None

    def test_不同用户_不串号(self):
        _cache_put(_cache_key("openai", "gpt-4o", "u1", "sk-x"), FakeModel())
        # 匿名(user_id=None)即使同 key 也不命中 u1 的缓存
        assert _cache_get(_cache_key("openai", "gpt-4o", None, "sk-x")) is None

    def test_容量上限_淘汰最旧(self):
        import time

        # 手动塞满:过期时间早的应被淘汰
        for i in range(300):
            k = _cache_key("p", f"m{i}", "u", f"k{i}")
            _MODEL_CACHE[k] = (FakeModel(), time.monotonic() + i)  # i 越大越晚过期
        _cache_put(_cache_key("p", "new", "u", "kn"), FakeModel())  # 触发淘汰
        assert len(_MODEL_CACHE) < 300
        # 最新写入的在
        assert _cache_get(_cache_key("p", "new", "u", "kn")) is not None
        # 最早过期的被清了
        assert _cache_get(_cache_key("p", "m0", "u", "k0")) is None
