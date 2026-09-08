"""netguard(SSRF 防护)的测试。

设计意图:
    fetch 工具的 URL 由模型决定、BYOK base_url 由用户决定,都是 SSRF 入口。
    这里锁定 netguard 的拒绝语义:私网/保留段/黑名单/坏协议一律 NetGuardError。
    域名解析路径通过 monkeypatch mock 掉 DNS,避免测试依赖网络,
    也才能测出"域名解析到私网 IP"这条最危险的路径。
"""

import pytest

from ryoshi.netguard import (
    NetGuardError,
    _is_private_ip,
    avalidate_outbound_url,
    resolve_safe_address,
)


class TestIpLiteral:
    """host 是 IP 字面量:不走 DNS,直接判定。"""

    @pytest.mark.parametrize(
        "url",
        [
            "http://127.0.0.1/x",
            "http://127.0.0.1:8000/api/keys",
            "http://10.0.0.1/",
            "http://172.16.0.1/",
            "http://192.168.1.1/",
            "http://169.254.169.254/latest/meta-data/",  # AWS metadata
            "http://0.0.0.0/",
            "http://100.64.0.1/",  # CGNAT
            "http://[::1]/",  # IPv6 loopback
            "http://[fe80::1]/",  # IPv6 link-local
            "http://[::ffff:127.0.0.1]/",  # IPv4-mapped IPv6 归一化后判定
        ],
    )
    async def test_私网与保留段_一律拒绝(self, url):
        with pytest.raises(NetGuardError):
            await avalidate_outbound_url(url)

    @pytest.mark.parametrize(
        "url",
        [
            "http://localhost/health",
            "https://metadata.google.internal/computeMetadata/v1/",
            "https://metadata.goog/",
        ],
    )
    async def test_黑名单域名_拒绝(self, url):
        with pytest.raises(NetGuardError):
            await avalidate_outbound_url(url)

    @pytest.mark.parametrize(
        "url",
        ["ftp://example.com/", "file:///etc/passwd", "gopher://127.0.0.1/", "not-a-url"],
    )
    async def test_非http协议_拒绝(self, url):
        with pytest.raises(NetGuardError):
            await avalidate_outbound_url(url)

    async def test_公网IP_放行(self):
        # 不应抛错;不真正发起请求,只校验
        await avalidate_outbound_url("https://93.184.216.34/")


class TestDomainResolution:
    """host 是域名:DNS 解析出的所有 IP 都必须公网。"""

    async def test_域名解析到私网IP_拒绝(self, monkeypatch):
        async def fake_resolve(host):
            return ["203.0.113.1", "10.0.0.7"]  # 多条 A 记录,混入私网

        monkeypatch.setattr("ryoshi.netguard._resolve_all_ips", fake_resolve)
        with pytest.raises(NetGuardError, match="10.0.0.7"):
            await avalidate_outbound_url("https://evil-rebind.example.com/")

    async def test_域名解析到公网IP_放行(self, monkeypatch):
        async def fake_resolve(host):
            return ["93.184.216.34"]

        monkeypatch.setattr("ryoshi.netguard._resolve_all_ips", fake_resolve)
        await avalidate_outbound_url("https://example.com/")

    async def test_域名无法解析_拒绝(self, monkeypatch):
        async def fake_resolve(host):
            raise NetGuardError(f"无法解析域名: {host}")

        monkeypatch.setattr("ryoshi.netguard._resolve_all_ips", fake_resolve)
        with pytest.raises(NetGuardError):
            await avalidate_outbound_url("https://nonexistent.invalid/")


class TestResolveSafeAddress:
    """resolve_safe_address:返回绑定的 (ip, port),供 fetch 直连。"""

    async def test_返回解析到的公网IP与默认端口(self, monkeypatch):
        async def fake_resolve(host):
            return ["93.184.216.34"]

        monkeypatch.setattr("ryoshi.netguard._resolve_all_ips", fake_resolve)
        ip, port = await resolve_safe_address("https://example.com/path")
        assert ip == "93.184.216.34"
        assert port == 443

    async def test_http默认80_显式端口优先(self, monkeypatch):
        async def fake_resolve(host):
            return ["93.184.216.34"]

        monkeypatch.setattr("ryoshi.netguard._resolve_all_ips", fake_resolve)
        assert (await resolve_safe_address("http://example.com/"))[1] == 80
        assert (await resolve_safe_address("https://example.com:8443/x"))[1] == 8443

    async def test_私网IP_不返回地址(self):
        with pytest.raises(NetGuardError):
            await resolve_safe_address("http://127.0.0.1:8000/api/keys")


class TestIsPrivateIp:
    def test_ipv4映射的ipv6_归一化后判定(self):
        import ipaddress

        assert _is_private_ip(ipaddress.ip_address("::ffff:127.0.0.1"))
        assert not _is_private_ip(ipaddress.ip_address("::ffff:93.184.216.34"))
