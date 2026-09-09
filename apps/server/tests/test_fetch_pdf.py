"""PDF 抓取路径测试(mock 网络,不发真实请求)。"""

from unittest.mock import AsyncMock, patch

import pytest

from ryoshi.tools.fetch import _looks_like_pdf, fetch_url


class TestLooksLikePdf:
    def test_pdf后缀识别(self):
        assert _looks_like_pdf("https://a.com/paper.pdf") is True
        assert _looks_like_pdf("https://a.com/paper.PDF") is True  # 大小写
        assert _looks_like_pdf("https://a.com/paper.pdf?v=2") is True

    def test_非PDF不误判(self):
        assert _looks_like_pdf("https://a.com/page.html") is False
        assert _looks_like_pdf("https://a.com/") is False
        # query 里带 pdf 字样的老式论文站
        assert _looks_like_pdf("https://a.com/get?file=report.pdf") is True


class TestPdfFetchFallback:
    async def test_Jina失败_降级本地pypdf(self):
        """Jina 超时(HTTPError)→ 走 _fetch_pdf_local(下载+解析)。"""
        with (
            patch("ryoshi.tools.fetch.avalidate_outbound_url", new=AsyncMock()),
            patch(
                "ryoshi.http.get_http_client"
            ) as gh,
        ):
            # Jina 请求抛超时
            gh.return_value.get = AsyncMock(side_effect=__import__("httpx").ConnectTimeout("t"))
            with patch("ryoshi.tools.fetch._fetch_pdf_local", new=AsyncMock()) as local:
                local.return_value = __import__("ryoshi.tools.fetch", fromlist=["FetchResult"]).FetchResult(
                    url="https://a.com/p.pdf", title="T", text="本地解析"
                )
                r = await fetch_url("https://a.com/p.pdf")
                assert r.text == "本地解析"
                local.assert_awaited_once()

    async def test_内网PDF被拒(self):
        """SSRF:内网 PDF 地址直接拒绝,两条路径都到不了。"""
        with patch("ryoshi.tools.fetch.avalidate_outbound_url", new=AsyncMock()) as av:
            from ryoshi.netguard import NetGuardError

            av.side_effect = NetGuardError("目标地址(10.0.0.5)指向私有/保留网段")
            with pytest.raises(NetGuardError):
                await fetch_url("http://10.0.0.5/secret.pdf")
