"""搜索结果缓存(Redis,带静默降级)。

设计意图:
    相同 query 在短时间内反复出现是常态(用户重试、regenerate、
    多人问同一热点)。搜索源按次计费(Tavily/Brave/Exa),不缓存
    等于白付钱;docker-compose 里 Redis 本就常驻。

    与限流(ratelimit)的关键差异:
      - 限流只在云端部署启用(RYOSHI_CLOUD_DEPLOYMENT);
        缓存**始终启用**——本地开发同样受益,且无 Redis 时
        静默穿透(不缓存也不报错),零风险。
      - 命中不能改变语义:SearchResults 是纯数据,缓存原样进出。

    缓存策略:
      - key: sc:{query 的 md5}:{max_results}:{search_depth}
        (include/exclude domains 影响结果,一并进 key)
      - TTL 15 分钟:搜索结果的时效性窗口,超过后宁可重搜也不用旧数据
      - 只缓存成功结果(降级链成功走到某一档的结果)
"""

import hashlib
import json
import logging
from typing import TYPE_CHECKING

from ryoshi.config import get_settings

if TYPE_CHECKING:  # 仅类型引用,运行时惰性导入(与项目其他模块一致)
    from ryoshi.tools.search import SearchResults

logger = logging.getLogger("ryoshi.searchcache")

# 缓存 TTL(秒)。15 分钟:热点问题足够省,时效性损失可接受。
CACHE_TTL_SECONDS = 15 * 60

# 全局 Redis 客户端(独立于限流的那个:连接参数相同但生命周期/用途独立,
# 避免"限流仅云端启用"的语义牵连缓存)
_redis = None
_redis_initialized = False


def _get_redis():
    """获取缓存用 Redis 客户端。不可用时返回 None(缓存穿透)。"""
    global _redis, _redis_initialized
    if _redis_initialized:
        return _redis

    _redis_initialized = True
    try:
        import redis.asyncio as aioredis

        _redis = aioredis.from_url(get_settings().redis_url, decode_responses=True)
        return _redis
    except Exception:
        logger.warning("Redis 不可用,搜索缓存降级为直连(每次真实搜索)")
        _redis = None
        return None


def _cache_key(
    query: str,
    max_results: int,
    search_depth: str,
    include_domains: list[str] | None,
    exclude_domains: list[str] | None,
) -> str:
    """构造缓存 key。参数全进哈希:任何一项不同都不命中。"""
    payload = json.dumps(
        {
            "q": query,
            "n": max_results,
            "d": search_depth,
            "inc": sorted(include_domains or []),
            "exc": sorted(exclude_domains or []),
        },
        ensure_ascii=False,
        sort_keys=True,
    )
    return f"sc:{hashlib.md5(payload.encode('utf-8')).hexdigest()}"


async def cache_get(
    query: str,
    max_results: int = 10,
    search_depth: str = "basic",
    include_domains: list[str] | None = None,
    exclude_domains: list[str] | None = None,
) -> "SearchResults | None":
    """查缓存。命中返回 SearchResults,未命中/不可用返回 None(穿透)。"""
    redis = _get_redis()
    if redis is None:
        return None
    try:
        import asyncio

        raw = await asyncio.wait_for(
            redis.get(_cache_key(query, max_results, search_depth, include_domains, exclude_domains)),
            timeout=2.0,
        )
    except Exception:
        # 任何 Redis 故障都不阻塞搜索
        return None
    if not raw:
        return None

    from ryoshi.tools.search import SearchResults

    try:
        return SearchResults.from_cache_json(raw)
    except Exception:
        # 缓存数据损坏(版本变更等)按未命中处理
        return None


async def cache_put(
    results: "SearchResults",
    max_results: int = 10,
    search_depth: str = "basic",
    include_domains: list[str] | None = None,
    exclude_domains: list[str] | None = None,
    query_override: str | None = None,
) -> None:
    """写缓存。失败静默(不影响主流程)。

    query_override:写 key 用请求时的 query 而非 results.query——
    个别搜索源(SearXNG)会改写返回的 query 字段,直接拿它做 key
    会与读取 key 错开,缓存永不命中。
    """
    redis = _get_redis()
    if redis is None:
        return
    try:
        import asyncio

        await asyncio.wait_for(
            redis.set(
                _cache_key(
                    query_override or results.query,
                    max_results,
                    search_depth,
                    include_domains,
                    exclude_domains,
                ),
                results.to_cache_json(),
                ex=CACHE_TTL_SECONDS,
            ),
            timeout=2.0,
        )
    except Exception:
        pass  # 缓存写失败仅损失性能,不记日志刷屏
