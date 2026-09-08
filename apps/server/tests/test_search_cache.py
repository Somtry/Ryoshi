"""搜索缓存的行为测试(mock Redis,不依赖真实实例)。

设计意图:
    缓存必须满足三条硬语义:
      1. 命中:同参数 query 第二次不触发真实搜索
      2. 参数不同(max_results/depth/domains)不误命中
      3. Redis 故障时静默穿透,搜索照常工作
"""


from ryoshi.tools import cache as search_cache
from ryoshi.tools.search import SearchResults


def _fake_results(query: str = "测试") -> SearchResults:
    from ryoshi.tools.search import SearchResult

    return SearchResults(
        results=[SearchResult(title="t", url="https://a.com", content="c")],
        query=query,
    )


class _FakeRedis:
    """内存 dict 版 Redis,模拟 get/set/ex。"""

    def __init__(self):
        self.store: dict[str, str] = {}
        self.get_calls = 0

    async def get(self, key):
        self.get_calls += 1
        return self.store.get(key)

    async def set(self, key, value, ex=None):
        self.store[key] = value


class TestSearchCache:
    async def test_命中缓存_不触发真实搜索(self, monkeypatch):
        fake = _FakeRedis()
        monkeypatch.setattr(search_cache, "_get_redis", lambda: fake)
        real_calls = []

        async def fake_search(*args, **kwargs):
            real_calls.append((args, kwargs))
            return _fake_results()

        import ryoshi.tools.search as search_mod

        monkeypatch.setattr(search_mod, "_search_with_fallback_inner", fake_search)

        await search_mod.search_with_fallback(query="rust vs go")
        await search_mod.search_with_fallback(query="rust vs go")
        assert len(real_calls) == 1  # 第二次走缓存
        assert fake.get_calls == 2

    async def test_参数不同_不误命中(self, monkeypatch):
        fake = _FakeRedis()
        monkeypatch.setattr(search_cache, "_get_redis", lambda: fake)
        real_calls = []

        async def fake_search(*args, **kwargs):
            real_calls.append((args, kwargs))
            return _fake_results()

        import ryoshi.tools.search as search_mod

        monkeypatch.setattr(search_mod, "_search_with_fallback_inner", fake_search)

        await search_mod.search_with_fallback(query="q", max_results=5)
        await search_mod.search_with_fallback(query="q", max_results=10)  # 不同参数
        await search_mod.search_with_fallback(query="q", search_depth="advanced")
        assert len(real_calls) == 3  # 每个不同参数组合都真实搜索

    async def test_redis故障_静默穿透(self, monkeypatch):
        # _get_redis 返回 None → 缓存层完全不参与
        monkeypatch.setattr(search_cache, "_get_redis", lambda: None)
        real_calls = []

        async def fake_search(*args, **kwargs):
            real_calls.append((args, kwargs))
            return _fake_results()

        import ryoshi.tools.search as search_mod

        monkeypatch.setattr(search_mod, "_search_with_fallback_inner", fake_search)

        r = await search_mod.search_with_fallback(query="x")
        assert r is not None
        assert len(real_calls) == 1

    async def test_缓存roundtrip_数据无损(self):
        results = _fake_results(query="往返")
        raw = results.to_cache_json()
        restored = SearchResults.from_cache_json(raw)
        assert restored.query == "往返"
        assert restored.results[0].url == "https://a.com"
