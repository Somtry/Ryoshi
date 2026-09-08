"""PostHog 反代:/relay/{path} → https://us.i.posthog.com/{path}。

设计意图:
    对应原项目 next.config 的 rewrites(前端把 PostHog 的 api_host 配成
    /relay,浏览器请求同源 /relay/*,由服务端转发到 PostHog US cloud)。
    好处:隐藏第三方域名、规避广告拦截器、US cloud 场景下省一次 DNS。

    前端行为(见 web/lib/analytics/posthog-client.ts):
      - 未配 VITE_POSTHOG_HOST 或 host 是 us.i.posthog.com → 走 /relay
      - EU/自托管 → 直连配置的 host
    因此本路由固定转发到 US cloud 端点;Vite dev proxy 与 nginx 都把
    /relay 指到本服务,三条链路(本地 dev / Docker / 云端)行为一致。

    安全考虑:
      - 只转发到固定的 PostHog 域名,不是开放代理(无 SSRF 面)
      - 剥掉 hop-by-hop header(connection/keep-alive 等),避免转发语义错乱
      - 不缓存、不落盘,流式请求(如 session recording)直接透传
"""

import httpx
from fastapi import APIRouter, Request
from fastapi.responses import Response

router = APIRouter(prefix="/relay", tags=["relay"])

#: PostHog US cloud 入口(与原项目 rewrites 的目标一致)
_POSTHOG_US_HOST = "https://us.i.posthog.com"

#: hop-by-hop header:只在相邻两个 HTTP 节点之间有意义,透传会导致语义错乱
# (见 RFC 2616 13.5.1;httpx 也会拒绝设置部分此类头)
_HOP_BY_HOP_HEADERS = {
    "connection",
    "keep-alive",
    "proxy-authenticate",
    "proxy-authorization",
    "te",
    "trailers",
    "transfer-encoding",
    "upgrade",
    "host",  # httpx 会按目标 host 重写
}

# 转发时保留的请求头:PostHog SDK 依赖内容类型与 UA 做 UA 解析
_FORWARD_REQUEST_HEADERS = {"content-type", "user-agent"}


@router.api_route("/{path:path}", methods=["GET", "POST", "OPTIONS"])
async def relay(request: Request, path: str) -> Response:
    """把 /relay/* 透明转发到 PostHog US cloud。

    query string、请求体原样透传;响应以原始 status/content-type 回传。
    """
    target = f"{_POSTHOG_US_HOST}/{path}"
    if request.url.query:
        target = f"{target}?{request.url.query}"

    headers = {
        k: v
        for k, v in request.headers.items()
        if k.lower() in _FORWARD_REQUEST_HEADERS
    }

    async with httpx.AsyncClient(timeout=30) as client:
        upstream = await client.request(
            request.method,
            target,
            headers=headers,
            content=await request.body(),
        )

    # 响应头同样剥 hop-by-hop;其余(如 content-type)透传
    resp_headers = {
        k: v
        for k, v in upstream.headers.items()
        if k.lower() not in _HOP_BY_HOP_HEADERS
    }
    return Response(
        content=upstream.content,
        status_code=upstream.status_code,
        headers=resp_headers,
    )
