"""SSRF 防护:统一的目标地址安全校验。

设计意图:
    任何"用户/模型可控的出站 URL"都是 SSRF 入口:
      - fetch 工具:模型可被网页内容诱导去抓内网(云 metadata、数据库、
        本服务的 /api/keys 等)
      - BYOK discover-models:用户可填任意 base_url
    两处原本各自为政(keys.py 里有一套私网检查,fetch 工具完全没有),
    这里抽成共享模块,单一实现、单一清单。

    两个能力层次:
      1. avalidate_outbound_url —— 纯校验(域名解析出的所有 IP 均须公网)。
         适合"先校验再照常请求"的场景(keys discover-models)。
      2. resolve_safe_address —— 校验 + 返回已解析的 (ip, port)。
         供 fetch_url 在 httpx 层绑定 IP 连接,实现"校验过的地址 = 连接的地址",
         从根上堵死 DNS rebinding(校验时解析到公网 IP、真连接时域名再解析
         回 127.0.0.1 的竞态)。

    失败统一抛 NetGuardError,调用方转成自己的错误形态
    (工具返回 error / HTTP 400)。
"""

import asyncio
import ipaddress
import socket
from urllib.parse import urlparse

# 私有/保留 IP 段(SSRF 防护;与原 api/keys.py 的清单一致)
_PRIVATE_NETWORKS = [
    ipaddress.ip_network("127.0.0.0/8"),      # loopback
    ipaddress.ip_network("10.0.0.0/8"),       # private
    ipaddress.ip_network("172.16.0.0/12"),    # private
    ipaddress.ip_network("192.168.0.0/16"),   # private
    ipaddress.ip_network("169.254.0.0/16"),   # link-local / 云 metadata (AWS/GCP)
    ipaddress.ip_network("0.0.0.0/8"),        # "this" 网络
    ipaddress.ip_network("100.64.0.0/10"),    # CGNAT 共享地址段
    ipaddress.ip_network("::1/128"),          # IPv6 loopback
    ipaddress.ip_network("fc00::/7"),         # IPv6 private
    ipaddress.ip_network("fe80::/10"),        # IPv6 link-local
    ipaddress.ip_network("::ffff:0:0/96"),    # IPv4-mapped IPv6(先归一化再查)
]

# 危险 host 黑名单(域名形态的 metadata 端点等)
_BLOCKED_HOSTS = {
    "localhost",
    "metadata.google.internal",
    "metadata.goog",
}

_DNS_TIMEOUT_SECONDS = 5.0


class NetGuardError(Exception):
    """目标地址不允许访问(私网/保留段/黑名单/无法解析)。"""


def _is_private_ip(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    """判断 IP 是否落在私网/保留段。IPv4-mapped IPv6 先归一化成 IPv4 再查。"""
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped is not None:
        ip = ip.ipv4_mapped
    return any(ip in net for net in _PRIVATE_NETWORKS)


async def _resolve_all_ips(host: str) -> list[str]:
    """异步解析 host 的所有 A/AAAA 记录(在默认 executor 里跑阻塞的 getaddrinfo)。

    返回 IP 字符串列表;无法解析抛 NetGuardError。
    """
    loop = asyncio.get_running_loop()
    try:
        addrinfo = await asyncio.wait_for(
            loop.run_in_executor(
                None,
                lambda: socket.getaddrinfo(host, None, socket.AF_UNSPEC, socket.SOCK_STREAM),
            ),
            timeout=_DNS_TIMEOUT_SECONDS,
        )
    except (TimeoutError, socket.gaierror, OSError) as exc:
        raise NetGuardError(f"无法解析域名: {host}") from exc
    return list({info[4][0] for info in addrinfo})


async def avalidate_outbound_url(url: str) -> None:
    """校验一个出站 URL 的目标地址安全(协议必须是 http/https)。

    检查:协议、host 黑名单、DNS 解析出的所有 IP 均不在私网段。
    通过返回 None,不通过抛 NetGuardError。

    注意:本校验只保证"校验时刻"的解析结果安全;存在 DNS rebinding 竞态。
    需要彻底防护的场景(fetch 工具)请用 resolve_safe_address 绑定 IP 连接。
    """
    host, _scheme = _parse_url(url)
    ips = await _resolve_all_ips(host)
    _check_host_and_ips(host, ips)


async def resolve_safe_address(url: str) -> tuple[str, int]:
    """校验 URL 并返回已解析的安全地址 (ip, port)。

    供 httpx 的 transport 层直接以 IP 建立连接(Host 头仍传域名),
    保证"校验过的地址 = 连接的地址",堵死 DNS rebinding。
    返回的 ip 保证不在私网/保留段。
    """
    host, scheme = _parse_url(url)
    port = 443 if scheme == "https" else 80
    # URL 里显式写了端口则尊重之(仅数字端口,已由 urlparse 保证)
    parsed = urlparse(url)
    if parsed.port is not None:
        port = parsed.port

    ips = await _resolve_all_ips(host)
    _check_host_and_ips(host, ips)

    # 全部解析结果都校验过了,取第一个用于连接
    return ips[0], port


def _parse_url(url: str) -> tuple[str, str]:
    """拆出 (host, scheme) 并做协议与黑名单检查。"""
    try:
        parsed = urlparse(url)
    except Exception as exc:
        raise NetGuardError("URL 格式无效") from exc
    if parsed.scheme not in ("http", "https"):
        raise NetGuardError(f"不支持的协议: {parsed.scheme or '(空)'}(仅允许 http/https)")
    host = parsed.hostname
    if not host:
        raise NetGuardError("URL 缺少 host")
    if host.lower() in _BLOCKED_HOSTS:
        raise NetGuardError("不允许访问该地址")
    return host, parsed.scheme


def _check_host_and_ips(host: str, ips: list[str]) -> None:
    """host 黑名单复查 + 逐个 IP 检查私网段(host 本身是 IP 字面量时 ips 即 [host])。"""
    if host.lower() in _BLOCKED_HOSTS:
        raise NetGuardError("不允许访问该地址")
    # host 是 IP 字面量:直接判定(不走 DNS)
    try:
        literal_ip = ipaddress.ip_address(host)
    except ValueError:
        literal_ip = None
    if literal_ip is not None:
        if _is_private_ip(literal_ip):
            raise NetGuardError(f"目标地址({host})指向私有/保留网段,不允许访问")
        return
    for ip_str in ips:
        try:
            ip = ipaddress.ip_address(ip_str)
        except ValueError:
            continue
        if _is_private_ip(ip):
            raise NetGuardError(f"目标地址({host})解析到私有/保留 IP({ip_str}),不允许访问")
