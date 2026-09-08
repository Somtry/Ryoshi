"""网页搜索工具。

设计意图:
    对应原项目 lib/tools/search.ts。这是智能体获取实时信息的主要手段。
    结构:
      - SearchResult / SearchResults: 统一的返回结构(与前端渲染对齐)
      - BaseSearchProvider:         各搜索源(Tavily/SearXNG/Brave/Exa)的抽象
      - TavilySearchProvider:       默认源,直接 HTTP 调用(不依赖第三方 SDK,
                                    与原项目 fetch 调用保持同样的请求体)

    Quick 模式下智能体强制 type="optimized"(即直接带内容摘要的结果),
    所以本文件先只实现这条路径;general/视频/图片搜索在阶段 4 补齐。
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

from ryoshi.config import get_settings
from ryoshi.http import get_http_client


@dataclass
class SearchResult:
    """一条搜索结果。content 是页面摘要,供 AI 直接引用作答。"""

    title: str
    url: str
    content: str = ""
    score: float = 0.0
    published_date: str | None = None


@dataclass
class SearchResults:
    """一次搜索的完整返回。images 供 Generative UI 渲染图片网格。"""

    results: list[SearchResult] = field(default_factory=list)
    images: list[dict[str, Any]] = field(default_factory=list)
    query: str = ""
    answer: str | None = None  # Tavily 直接给的答案摘要

    def to_dict(self) -> dict[str, Any]:
        """转成工具输出 JSON(会作为 search 工具的返回进入消息流与持久化)。

        关键:必须带 state="complete"——前端 SearchSection 靠这个字段判断
        搜索是否完成、是否渲染结果列表(对应原项目流式搜索工具的完成帧)。
        """
        return {
            "state": "complete",
            "results": [
                {
                    "title": r.title,
                    "url": r.url,
                    "content": r.content,
                    "score": r.score,
                    **({"publishedDate": r.published_date} if r.published_date else {}),
                }
                for r in self.results
            ],
            "images": self.images,
            "query": self.query,
            **({"answer": self.answer} if self.answer else {}),
        }

    def to_cache_json(self) -> str:
        """序列化为缓存条目(Redis 存取;与 to_dict 分离,格式可独立演进)。"""
        import json

        return json.dumps(
            {
                "results": [
                    {
                        "title": r.title,
                        "url": r.url,
                        "content": r.content,
                        "score": r.score,
                        "published_date": r.published_date,
                    }
                    for r in self.results
                ],
                "images": self.images,
                "query": self.query,
                "answer": self.answer,
            },
            ensure_ascii=False,
        )

    @classmethod
    def from_cache_json(cls, raw: str) -> "SearchResults":
        """从缓存条目还原。字段缺失/多余都容忍(缓存格式向前兼容)。"""
        import json

        data = json.loads(raw)
        return cls(
            results=[
                SearchResult(
                    title=r.get("title", ""),
                    url=r.get("url", ""),
                    content=r.get("content", ""),
                    score=r.get("score", 0.0),
                    published_date=r.get("published_date"),
                )
                for r in data.get("results", [])
            ],
            images=data.get("images", []),
            query=data.get("query", ""),
            answer=data.get("answer"),
        )


class SearchProviderError(Exception):
    """搜索源调用失败(网络错误或非 2xx)。带 HTTP 状态以便上层做降级判断。"""

    def __init__(self, message: str, status: int | None = None):
        super().__init__(message)
        self.status = status


class BaseSearchProvider(ABC):
    """搜索源抽象。所有源实现同一个 search 接口,便于互换与降级。"""

    @abstractmethod
    async def search(
        self,
        query: str,
        max_results: int = 10,
        search_depth: str = "basic",
        include_domains: list[str] | None = None,
        exclude_domains: list[str] | None = None,
    ) -> SearchResults:
        ...


class TavilySearchProvider(BaseSearchProvider):
    """Tavily 搜索(默认源)。请求体与原项目 tavily.ts 完全一致。"""

    _ENDPOINT = "https://api.tavily.com/search"

    async def search(
        self,
        query: str,
        max_results: int = 10,
        search_depth: str = "basic",
        include_domains: list[str] | None = None,
        exclude_domains: list[str] | None = None,
    ) -> SearchResults:
        settings = get_settings()
        if not settings.tavily_api_key:
            raise SearchProviderError("未配置 TAVILY_API_KEY")

        include_domains = include_domains or []
        exclude_domains = exclude_domains or []

        # Tavily 要求 query 至少 5 个字符,不足则右侧补空格(与原项目一致)
        filled_query = query if len(query) >= 5 else query + " " * (5 - len(query))

        # 云端部署时全站排除低价值聚合页(与原项目 CLOUD_EXCLUDED_DOMAINS 一致)
        if settings.ryoshi_cloud_deployment:
            exclude_domains = list({*exclude_domains, "instagram.com"})

        payload = {
            "api_key": settings.tavily_api_key,
            "query": filled_query,
            "max_results": max(max_results, 5),
            "search_depth": search_depth,
            "include_images": True,
            "include_image_descriptions": True,
            "include_answers": True,
            "include_domains": include_domains,
            "exclude_domains": exclude_domains,
        }

        client = get_http_client()
        resp = await client.post(self._ENDPOINT, json=payload)
        if resp.status_code != 200:
            raise SearchProviderError(
                f"Tavily API 错误: {resp.status_code}", status=resp.status_code
            )

        data = resp.json()
        results = [
            SearchResult(
                title=r.get("title", ""),
                url=r.get("url", ""),
                content=r.get("content", ""),
                score=r.get("score", 0.0),
                published_date=r.get("published_date"),
            )
            for r in data.get("results", [])
        ]

        # 图片:尽量按标题匹配回源文章 URL,让 UI 能链接到原文而非图床
        title_to_url = {r.title: r.url for r in results if r.title and r.url}
        images: list[dict[str, Any]] = []
        for img in data.get("images", []) or []:
            if isinstance(img, dict):
                desc = img.get("description", "")
                if not desc:
                    continue
                entry: dict[str, Any] = {"url": img.get("url", ""), "description": desc}
                if img.get("title"):
                    entry["title"] = img["title"]
                    if img["title"] in title_to_url:
                        entry["sourceUrl"] = title_to_url[img["title"]]
                images.append(entry)
            elif isinstance(img, str):
                images.append({"url": img})

        return SearchResults(
            results=results,
            images=images,
            query=query,
            answer=data.get("answer"),
        )


class SearXNGSearchProvider(BaseSearchProvider):
    """SearXNG 自托管搜索(本地 Docker 或内网实例)。请求/响应对应原项目 searxng.ts。"""

    async def search(
        self,
        query: str,
        max_results: int = 10,
        search_depth: str = "basic",
        include_domains: list[str] | None = None,
        exclude_domains: list[str] | None = None,
    ) -> SearchResults:
        settings = get_settings()
        if not settings.searxng_base_url:
            raise SearchProviderError("未配置 SEARXNG_BASE_URL")

        params: dict[str, str] = {
            "q": query,
            "format": "json",
            "categories": "general,images",
        }
        if search_depth == "advanced":
            params.update({"time_range": "", "safesearch": "0", "engines": "google,bing,duckduckgo,wikipedia"})
        else:
            params.update({"time_range": "year", "safesearch": "1", "engines": "google,bing"})
        if include_domains:
            params["site"] = ",".join(include_domains)

        resp = await get_http_client().get(
            f"{settings.searxng_base_url}/search",
            params=params,
            headers={"Accept": "application/json"},
        )
        if resp.status_code != 200:
            raise SearchProviderError(f"SearXNG API 错误: {resp.status_code}", status=resp.status_code)

        data = resp.json()
        all_results = data.get("results", [])
        general = [r for r in all_results if not r.get("img_src")][:max_results]
        images = [
            {"url": r.get("img_src", ""), "description": r.get("content", "")}
            for r in all_results
            if r.get("img_src")
        ][:max_results]

        return SearchResults(
            results=[
                SearchResult(title=r.get("title", ""), url=r.get("url", ""), content=r.get("content", ""), score=0.0)
                for r in general
            ],
            images=images,
            query=data.get("query", query),
        )


class BraveSearchProvider(BaseSearchProvider):
    """Brave 搜索。对应原项目 brave.ts。"""

    _ENDPOINT = "https://api.search.brave.com/res/v1/web/search"

    async def search(
        self,
        query: str,
        max_results: int = 10,
        search_depth: str = "basic",
        include_domains: list[str] | None = None,
        exclude_domains: list[str] | None = None,
    ) -> SearchResults:
        settings = get_settings()
        if not settings.brave_api_key:
            raise SearchProviderError("未配置 BRAVE_API_KEY")

        headers = {"Accept": "application/json", "X-Subscription-Token": settings.brave_api_key}
        params: dict[str, str] = {"q": query, "count": str(max_results), "safesearch": "moderate"}
        if include_domains:
            params["site"] = ",".join(include_domains)

        resp = await get_http_client().get(self._ENDPOINT, params=params, headers=headers)
        if resp.status_code != 200:
            raise SearchProviderError(f"Brave API 错误: {resp.status_code}", status=resp.status_code)

        data = resp.json()
        web_results = data.get("web", {}).get("results", [])
        return SearchResults(
            results=[
                SearchResult(
                    title=r.get("title", ""),
                    url=r.get("url", ""),
                    content=r.get("description", ""),
                    score=r.get("score", 0.0),
                )
                for r in web_results[:max_results]
            ],
            images=[],
            query=query,
        )


class ExaSearchProvider(BaseSearchProvider):
    """Exa 神经搜索。对应原项目 exa.ts。"""

    _ENDPOINT = "https://api.exa.ai/search"

    async def search(
        self,
        query: str,
        max_results: int = 10,
        search_depth: str = "basic",
        include_domains: list[str] | None = None,
        exclude_domains: list[str] | None = None,
    ) -> SearchResults:
        settings = get_settings()
        if not settings.exa_api_key:
            raise SearchProviderError("未配置 EXA_API_KEY")

        payload: dict[str, Any] = {
            "query": query,
            "numResults": max_results,
            "contents": {"text": {"maxCharacters": 1000}},
        }
        if include_domains:
            payload["includeDomains"] = include_domains
        if exclude_domains:
            payload["excludeDomains"] = exclude_domains

        headers = {"x-api-key": settings.exa_api_key, "Content-Type": "application/json"}
        resp = await get_http_client().post(self._ENDPOINT, json=payload, headers=headers)
        if resp.status_code != 200:
            raise SearchProviderError(f"Exa API 错误: {resp.status_code}", status=resp.status_code)

        data = resp.json()
        return SearchResults(
            results=[
                SearchResult(
                    title=r.get("title", ""),
                    url=r.get("url", ""),
                    content=(r.get("text") or "")[:1000],
                    score=r.get("score", 0.0),
                    published_date=r.get("publishedDate"),
                )
                for r in data.get("results", [])
            ],
            images=[],
            query=query,
        )


# ---- 降级链 ----
# 与原项目 search.ts 的降级策略对应:
#   默认源由 SEARCH_API 指定(默认 tavily);失败(可恢复错误)时按降级链依次尝试。
#   可恢复错误 = 网络超时/5xx/限流;4xx 参数错误不降级(重试无意义)。
_PROVIDERS: dict[str, type[BaseSearchProvider]] = {
    "tavily": TavilySearchProvider,
    "searxng": SearXNGSearchProvider,
    "brave": BraveSearchProvider,
    "exa": ExaSearchProvider,
}

# 降级顺序:优先同类型的高质量源,最后兜底本地 SearXNG
_FALLBACK_ORDER = ["tavily", "brave", "exa", "searxng"]


def _is_recoverable(exc: Exception) -> bool:
    """判断是否可恢复错误(网络/5xx/限流),可降级;4xx 参数错误不降级。"""
    if isinstance(exc, SearchProviderError):
        return exc.status is None or exc.status >= 500 or exc.status == 429
    return True  # 网络异常等


async def search_with_fallback(
    query: str,
    max_results: int = 10,
    search_depth: str = "basic",
    include_domains: list[str] | None = None,
    exclude_domains: list[str] | None = None,
) -> SearchResults:
    """带降级链的搜索。默认源失败(可恢复)时按 _FALLBACK_ORDER 依次尝试。

    外层套 Redis 缓存(tools/cache.py):同参数 query 在 TTL 内直接命中,
    不再消耗搜索源配额;Redis 不可用时静默穿透。
    """
    from ryoshi.tools.cache import cache_get, cache_put

    cached = await cache_get(
        query, max_results, search_depth, include_domains, exclude_domains
    )
    if cached is not None:
        return cached

    result = await _search_with_fallback_inner(
        query, max_results, search_depth, include_domains, exclude_domains
    )
    # 写入 key 用"本次请求的 query"显式覆盖(个别搜索源会改写 result.query,
    # 拿它构造 key 会与读取 key 错开 → 缓存永远不命中)
    await cache_put(
        result,
        max_results,
        search_depth,
        include_domains,
        exclude_domains,
        query_override=query,
    )
    return result


async def _search_with_fallback_inner(
    query: str,
    max_results: int = 10,
    search_depth: str = "basic",
    include_domains: list[str] | None = None,
    exclude_domains: list[str] | None = None,
) -> SearchResults:
    """降级链本体(缓存未命中时执行)。"""
    settings = get_settings()
    preferred = getattr(settings, "search_api", None) or "tavily"

    # 构造尝试顺序:默认源在前,其余按降级链
    order = [preferred] + [p for p in _FALLBACK_ORDER if p != preferred]
    last_error: Exception | None = None

    for name in order:
        provider_cls = _PROVIDERS.get(name)
        if provider_cls is None:
            continue
        provider = provider_cls()
        try:
            return await provider.search(
                query=query,
                max_results=max_results,
                search_depth=search_depth,
                include_domains=include_domains,
                exclude_domains=exclude_domains,
            )
        except Exception as exc:
            last_error = exc
            if not _is_recoverable(exc):
                raise  # 4xx 等不可恢复,直接抛
            print(f"[ryoshi] 搜索源 {name} 失败({exc}),尝试降级")
            continue

    raise SearchProviderError(f"所有搜索源均失败: {last_error}")


def get_default_provider() -> BaseSearchProvider:
    """取默认搜索源(由 SEARCH_API 配置,默认 tavily)。"""
    settings = get_settings()
    name = getattr(settings, "search_api", None) or "tavily"
    return _PROVIDERS.get(name, TavilySearchProvider)()
