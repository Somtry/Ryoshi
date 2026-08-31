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

import httpx

from ryoshi.config import get_settings


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
        """转成工具输出 JSON(会作为 search 工具的返回进入消息流与持久化)。"""
        return {
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

        async with httpx.AsyncClient(timeout=30) as client:
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


def get_default_provider() -> BaseSearchProvider:
    """取默认搜索源。阶段 3 只有 Tavily;阶段 4 按 SEARCH_API 配置扩展到多源。"""
    return TavilySearchProvider()
