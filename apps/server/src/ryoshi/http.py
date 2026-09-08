"""共享的 httpx.AsyncClient(进程级连接池)。

设计意图:
    项目里五处出站 HTTP(搜索 4 provider、网页抓取、JWKS 拉取、
    BYOK 模型发现、PostHog relay)原本各自 async with httpx.AsyncClient(),
    每次请求都完整走一遍 TCP+TLS 握手——高并发下延迟与句柄开销显著,
    还可能同时打开大量短连接触发对端限流。

    这里提供进程级单例:连接复用(HTTP/1.1 keep-alive)、统一超时与
    生命周期管理。由 main.py 的 lifespan 在启动时初始化、关闭时释放;
    未初始化时(脚本/测试单独调用工具函数)惰性兜底创建,不报错。

    注意:fetch 工具的 SSRF 防护不受影响——它按"校验过的 IP 直连",
    用的是自己的 client(每请求一个,因为连接目标各不相同);
    本单例只服务"目标固定/由配置决定"的出站调用。
"""

import httpx

# 进程级共享客户端;None 表示尚未初始化(惰性创建见 get_http_client)
_client: httpx.AsyncClient | None = None

# 统一超时:连接 5s / 读 30s / 写 30s / 池等待 10s。
# 搜索与抓取的既有代码都用 timeout=30,保持读超时一致。
_TIMEOUT = httpx.Timeout(connect=5.0, read=30.0, write=30.0, pool=10.0)

# 连接池上限:与 DB 引擎的 pool_size 对齐,避免突发流量打爆对端
_LIMITS = httpx.Limits(max_connections=30, max_keepalive_connections=10)


def init_http_client() -> httpx.AsyncClient:
    """创建共享客户端(应用启动时调用;重复调用返回已有实例)。"""
    global _client
    if _client is None or _client.is_closed:
        _client = httpx.AsyncClient(timeout=_TIMEOUT, limits=_LIMITS)
    return _client


async def close_http_client() -> None:
    """关闭共享客户端(应用关闭时调用;未初始化时静默)。"""
    global _client
    if _client is not None and not _client.is_closed:
        await _client.aclose()
    _client = None


def get_http_client() -> httpx.AsyncClient:
    """取共享客户端。

    未初始化时惰性创建(脚本/测试场景没有 lifespan);进程退出时
    未关闭会有一条 ResourceWarning,无害。
    """
    return init_http_client()
