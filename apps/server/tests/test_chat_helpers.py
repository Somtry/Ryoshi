"""chat 路由辅助函数的测试。

设计意图:
    _client_ip 是访客限流的分桶依据——分桶错了,云端所有匿名用户会被合进
    同一个 10 次/天的配额桶(全站一天只能匿名提问 10 次)。这里锁定它的
    取值语义:X-Forwarded-For 取**最后一个**条目(可信代理追加的),
    绝不取第一个(客户端可伪造)。
"""

from ryoshi.api.chat import _client_ip


class _Client:
    def __init__(self, host: str):
        self.host = host


class _Request:
    """最小化的 starlette.Request 替身:只提供 headers 与 client。"""

    def __init__(self, headers: dict[str, str] | None = None, host: str = "127.0.0.1"):
        self.headers = headers or {}
        self.client = _Client(host)


class TestClientIp:
    def test_无代理头_用直连地址(self):
        assert _client_ip(_Request(host="192.168.1.5")) == "192.168.1.5"

    def test_单条xff_取该条(self):
        req = _Request(headers={"x-forwarded-for": "203.0.113.7"}, host="172.17.0.5")
        assert _client_ip(req) == "203.0.113.7"

    def test_多条xff_取最后一个_不取客户端伪造的第一个(self):
        # 客户端自带伪造 XFF("1.2.3.4"),nginx 在尾部追加真实 IP。
        # 取第一个=攻击者自选限流桶;取最后一个=真实客户端 IP。
        req = _Request(
            headers={"x-forwarded-for": "1.2.3.4, 198.51.100.9"},
            host="172.17.0.5",
        )
        assert _client_ip(req) == "198.51.100.9"

    def test_xff_含空白_正确去空白(self):
        req = _Request(
            headers={"x-forwarded-for": "1.2.3.4 ,  198.51.100.9 "},
            host="172.17.0.5",
        )
        assert _client_ip(req) == "198.51.100.9"

    def test_xff_为空串_兜底直连地址(self):
        req = _Request(headers={"x-forwarded-for": ""}, host="172.17.0.5")
        assert _client_ip(req) == "172.17.0.5"

    def test_xff_只有空段_兜底直连地址(self):
        req = _Request(headers={"x-forwarded-for": ", ,"}, host="172.17.0.5")
        assert _client_ip(req) == "172.17.0.5"
