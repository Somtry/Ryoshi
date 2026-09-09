"""feedback/upload 限流 scope 的接线测试(mock Redis 计数)。"""

from unittest.mock import AsyncMock, patch

from ryoshi.ratelimit import (
    FEEDBACK_DAILY_LIMIT,
    UPLOAD_DAILY_LIMIT,
    RateLimitResult,
    check_feedback_limit,
    check_upload_limit,
)


def _result(allowed: bool) -> RateLimitResult:
    return RateLimitResult(
        allowed=allowed, limit=10, used=10 if not allowed else 1,
        remaining=0 if not allowed else 9, reset_at=0, enforced=True,
    )


class TestNewScopes:
    async def test_feedback_超限_拒绝(self):
        with patch(
            "ryoshi.ratelimit._check_limit",
            new=AsyncMock(return_value=_result(False)),
        ) as mock:
            r = await check_feedback_limit("1.2.3.4")
            assert r.allowed is False
            # scope 与上限传对
            assert mock.call_args.args == ("feedback", "1.2.3.4", FEEDBACK_DAILY_LIMIT)

    async def test_upload_scope_参数正确(self):
        with patch(
            "ryoshi.ratelimit._check_limit",
            new=AsyncMock(return_value=_result(True)),
        ) as mock:
            r = await check_upload_limit("1.2.3.4")
            assert r.allowed is True
            assert mock.call_args.args == ("upload", "1.2.3.4", UPLOAD_DAILY_LIMIT)
