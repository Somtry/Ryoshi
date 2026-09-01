"""限流:基于 Redis 的三层配额控制(对应原项目 lib/rate-limit/)。

设计意图:
    与原项目三层限流一一对应:
      1. 访客限流(guest-limit): 按 IP,每天 10 次,超限返回 401 提示登录
      2. 用户总量限流(chat-limits): 按 userId,每天 100 次,超限返回 429
      3. Adaptive 模式限流(adaptive-limit): 按 userId,每天 30 次,超限返回 429

    仅在云端部署(RYOSHI_CLOUD_DEPLOYMENT=true)且配置了 Redis 时生效;
    本地开发/未配置时全部放行(enforced=False),不阻塞主流程。

    Redis key 格式与原项目一致: rl:{scope}:{identifier}:{date}
    过期时间设为到 UTC 午夜,实现"每日配额"语义。
"""

import logging
import time
from dataclasses import dataclass
from datetime import UTC, datetime

from ryoshi.config import get_settings

logger = logging.getLogger("ryoshi.ratelimit")

# 全局 Redis 客户端,惰性初始化
_redis = None
_redis_initialized = False


def _get_redis():
    """获取 Redis 客户端。未配置时返回 None(限流不生效)。"""
    global _redis, _redis_initialized
    if _redis_initialized:
        return _redis

    _redis_initialized = True
    s = get_settings()
    if not s.ryoshi_cloud_deployment:
        _redis = None
        return None

    try:
        import redis.asyncio as aioredis

        _redis = aioredis.from_url(s.redis_url, decode_responses=True)
        return _redis
    except Exception:
        logger.exception("Redis 连接失败,限流降级为放行")
        _redis = None
        return None


def _seconds_until_midnight() -> int:
    """到 UTC 午夜的秒数。"""
    now = datetime.now(UTC)
    midnight = now.replace(hour=0, minute=0, second=0, microsecond=0)
    midnight = midnight.replace(day=midnight.day)  # 下一天
    from datetime import timedelta

    next_midnight = midnight + timedelta(days=1)
    return max(1, int((next_midnight - now).total_seconds()))


def _midnight_timestamp() -> int:
    """下一个 UTC 午夜的 Unix 时间戳。"""
    return int(time.time()) + _seconds_until_midnight()


def _today_key() -> str:
    """当前 UTC 日期字符串(YYYY-MM-DD),用于 Redis key。"""
    return datetime.now(UTC).strftime("%Y-%m-%d")


@dataclass
class RateLimitResult:
    """限流检查结果。"""

    allowed: bool
    limit: int
    used: int
    remaining: int
    reset_at: int  # Unix 时间戳
    enforced: bool  # 是否真正执行了 Redis 检查(非云端/未配置时为 False)


async def _check_limit(
    scope: str, identifier: str, daily_limit: int
) -> RateLimitResult:
    """统一的限流检查。Redis INCR + 首次设置 TTL 到午夜。"""
    redis = _get_redis()
    if redis is None:
        return RateLimitResult(
            allowed=True, limit=daily_limit, used=0,
            remaining=daily_limit, reset_at=0, enforced=False,
        )

    key = f"rl:{scope}:{identifier}:{_today_key()}"
    try:
        import asyncio

        count = await asyncio.wait_for(redis.incr(key), timeout=3.0)
        if count == 1:
            await redis.expire(key, _seconds_until_midnight())

        remaining = max(0, daily_limit - count)
        return RateLimitResult(
            allowed=count <= daily_limit,
            limit=daily_limit,
            used=count,
            remaining=remaining,
            reset_at=_midnight_timestamp(),
            enforced=True,
        )
    except Exception:
        # Redis 故障时放行,不阻塞用户
        logger.exception("Redis 限流检查失败,放行")
        return RateLimitResult(
            allowed=True, limit=daily_limit, used=0,
            remaining=daily_limit, reset_at=0, enforced=False,
        )


# ---- 三层限流(对应原项目三个文件) ----

#: 访客每日上限(对应原项目 GUEST_CHAT_DAILY_LIMIT,默认 10)
GUEST_DAILY_LIMIT = 10
#: 登录用户每日上限(对应原项目 OVERALL_CHAT_DAILY_LIMIT,默认 100)
USER_DAILY_LIMIT = 100
#: Adaptive 模式每日上限(对应原项目 ADAPTIVE_CHAT_DAILY_LIMIT,默认 30)
ADAPTIVE_DAILY_LIMIT = 30


async def check_guest_limit(ip: str) -> RateLimitResult:
    """访客限流:按 IP,每天 10 次。"""
    return await _check_limit("guest:chat", ip, GUEST_DAILY_LIMIT)


async def check_overall_chat_limit(user_id: str) -> RateLimitResult:
    """用户总量限流:按 userId,每天 100 次。"""
    return await _check_limit("chat", user_id, USER_DAILY_LIMIT)


async def check_adaptive_limit(user_id: str) -> RateLimitResult:
    """Adaptive 模式限流:按 userId,每天 30 次。"""
    return await _check_limit("adaptive:chat", user_id, ADAPTIVE_DAILY_LIMIT)
