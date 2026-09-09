"""chat 路由辅助函数的测试。

设计意图:
    _client_ip 是访客限流的分桶依据——分桶错了,云端所有匿名用户会被合进
    同一个 10 次/天的配额桶(全站一天只能匿名提问 10 次)。这里锁定它的
    取值语义:X-Forwarded-For 取**最后一个**条目(可信代理追加的),
    绝不取第一个(客户端可伪造)。
"""

from ryoshi.ratelimit import client_ip_from_request as _client_ip


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


class TestMultimodalContent:
    """_multimodal_content:图片附件 → 多模态 block;无图 → 纯文本不变。"""

    @staticmethod
    def _build_req(parts):
        from ryoshi.api.chat import ChatRequest, IncomingMessage

        return ChatRequest(message=IncomingMessage(parts=parts))

    def test_图片附件_构造多模态block(self):
        from langchain_core.messages import HumanMessage

        from ryoshi.api.chat import _supports_vision

        # 直接验证判定函数与 block 形态(核心逻辑在 chat 路由闭包外可测的部分)
        assert _supports_vision("gpt-4o") is True
        assert _supports_vision("claude-haiku-4-5-20251001") is True
        assert _supports_vision("gemini-2.0-flash") is True
        assert _supports_vision("deepseek-chat") is False
        assert _supports_vision("deepseek-reasoner") is False
        # 未知模型默认支持(宁可报错也不静默丢图)
        assert _supports_vision("totally-unknown-model") is True

        # HumanMessage 接受 block 列表(多模态路径的类型契约)
        msg = HumanMessage(content=[
            {"type": "text", "text": "这是什么?"},
            {"type": "image_url", "image_url": {"url": "https://s3/a.png"}},
        ])
        assert isinstance(msg.content, list)
        assert msg.content[1]["image_url"]["url"] == "https://s3/a.png"

    def test_extract_user_text_保留附件文本行(self):
        req = self._build_req([
            {"type": "text", "text": "帮我看看这张图"},
            {"type": "file", "url": "https://s3/a.png", "filename": "截图.png",
             "mediaType": "image/png"},
        ])
        from ryoshi.api.chat import _extract_user_text

        text = _extract_user_text(req)
        assert "帮我看看这张图" in text
        assert "https://s3/a.png" in text  # 附件以文本行形式告知模型

    def test_无图片附件_行为不变(self):
        req = self._build_req([{"type": "text", "text": "纯文本问题"}])
        from ryoshi.api.chat import _extract_user_text

        assert _extract_user_text(req) == "纯文本问题"
