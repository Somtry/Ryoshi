"""网页内容抓取工具。

设计意图:
    对应原项目 lib/tools/fetch.ts。当用户消息里直接给出 URL 时,
    智能体用本工具取回该页正文供作答,而不是先去搜索。

    原项目有两种抓取类型:
      regular —— 直接 HTTP 抓 HTML 并提取正文(快,适用于大多数网页)
      api     —— 走 Jina Reader / Tavily Extract(用于 PDF 与 JS 渲染页)
    Quick 模式默认且仅用 regular,这里先实现这条路径;api 路径在阶段 4 补。

    HTML 正文提取:原项目用 jsdom + Readability。Python 侧用标准库 html.parser
    做"去标签留文本"的轻量提取——对 Quick 模式"拿到正文喂给模型"的目标足够,
    且零额外重依赖。若后续需要更接近 Readability 的正文识别,可换 trafilatura。
"""

import re
from dataclasses import dataclass
from html.parser import HTMLParser

import httpx

# 正文长度上限(与原项目 CONTENT_CHARACTER_LIMIT 一致,超出截断)
CONTENT_CHARACTER_LIMIT = 8000

# 抓取时声明的 Accept,模拟浏览器以拿到 HTML 而非被某些站点拒绝
_ACCEPT_HEADER = "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"


class _TextExtractor(HTMLParser):
    """去掉 HTML 标签、脚本、样式,只保留可读文本的解析器。"""

    # 这些标签的内容一律丢弃(脚本/样式/导航等非正文)
    _SKIP_TAGS = {"script", "style", "noscript", "head", "title", "meta", "link"}

    def __init__(self) -> None:
        super().__init__()
        self._parts: list[str] = []
        self._skip_depth = 0

    def handle_starttag(self, tag: str, attrs: list) -> None:
        if tag in self._SKIP_TAGS:
            self._skip_depth += 1
        # 块级标签前后补换行,避免文字粘连
        elif self._skip_depth == 0 and tag in ("p", "div", "br", "li", "tr", "h1", "h2", "h3"):
            self._parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in self._SKIP_TAGS and self._skip_depth > 0:
            self._skip_depth -= 1

    def handle_data(self, data: str) -> None:
        if self._skip_depth == 0:
            self._parts.append(data)

    def get_text(self) -> str:
        text = "".join(self._parts)
        # 折叠多余空白与空行,得到干净正文
        text = re.sub(r"[ \t]+", " ", text)
        text = re.sub(r"\n\s*\n+", "\n\n", text)
        return text.strip()


@dataclass
class FetchResult:
    """抓取结果。title 与 text 供 AI 阅读,url 回显来源。"""

    url: str
    title: str
    text: str

    def to_dict(self) -> dict:
        return {"url": self.url, "title": self.title, "text": self.text}


def _extract_title(html: str) -> str:
    match = re.search(r"<title[^>]*>(.*?)</title>", html, re.IGNORECASE | re.DOTALL)
    return match.group(1).strip() if match else ""


async def fetch_url(url: str) -> FetchResult:
    """抓取一个 URL 并提取正文。

    只支持 HTML / 纯文本;遇到 PDF 等其他类型抛错(Quick 模式下
    智能体的 prompt 已被告知 PDF 要用 api 类型,而 api 路径在阶段 4 实现)。
    """
    async with httpx.AsyncClient(
        timeout=30,
        follow_redirects=True,
        headers={"Accept": _ACCEPT_HEADER, "User-Agent": "Ryoshi/0.1 (+fetch)"},
    ) as client:
        resp = await client.get(url)

    if resp.status_code != 200:
        raise ValueError(f"抓取失败: HTTP {resp.status_code}")

    content_type = (resp.headers.get("content-type") or "").lower()
    body = resp.text

    if "text/html" in content_type or "application/xhtml" in content_type:
        extractor = _TextExtractor()
        extractor.feed(body)
        text = extractor.get_text()
        title = _extract_title(body)
    elif "text/plain" in content_type or "application/json" in content_type:
        text = body
        title = ""
    else:
        raise ValueError(f"不支持的内容类型: {content_type}")

    # 超长截断(与原项目一致,避免把整页塞进上下文)
    if len(text) > CONTENT_CHARACTER_LIMIT:
        text = text[:CONTENT_CHARACTER_LIMIT] + "...[truncated]"

    return FetchResult(url=url, title=title, text=text)
