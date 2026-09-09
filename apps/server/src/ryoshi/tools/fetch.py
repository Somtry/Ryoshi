"""网页内容抓取工具。

设计意图:
    对应原项目 lib/tools/fetch.ts。当用户消息里直接给出 URL 时,
    智能体用本工具取回该页正文供作答,而不是先去搜索。

    原项目有两种抓取类型:
      regular —— 直接 HTTP 抓 HTML 并提取正文(快,适用于大多数网页)
      api     —— 走 Jina Reader(用于 PDF 与 JS 渲染页)
    两条路径都已实现:URL 形态/响应头判定为 PDF 时自动切 Jina。

    HTML 正文提取:原项目用 jsdom + Readability。Python 侧用标准库 html.parser
    做"去标签留文本"的轻量提取——对 Quick 模式"拿到正文喂给模型"的目标足够,
    且零额外重依赖。若后续需要更接近 Readability 的正文识别,可换 trafilatura。

    SSRF 防护:
      URL 由模型决定,可被网页内容诱导。抓取前必须过 ryoshi.netguard:
      私网/保留段/云 metadata 一律拒绝;并且用"校验时解析到的 IP"直连
      (Host 头仍传域名,保证 TLS/SNI 与虚拟主机路由正常),
      堵死 DNS rebinding(校验与连接之间域名被切换解析)。
"""

import re
from dataclasses import dataclass
from html.parser import HTMLParser
from urllib.parse import urlsplit

import httpx

from ryoshi.netguard import avalidate_outbound_url, resolve_safe_address

# 正文长度上限(与原项目 CONTENT_CHARACTER_LIMIT 一致,超出截断)
CONTENT_CHARACTER_LIMIT = 8000

# 抓取时声明的 Accept,模拟浏览器以拿到 HTML 而非被某些站点拒绝
_ACCEPT_HEADER = "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"


class _TextExtractor(HTMLParser):
    """去掉 HTML 标签、脚本、样式,只保留可读文本的解析器。"""

    # 这些标签的内容一律丢弃(脚本/样式/导航等非正文)。frozenset:类属性
    # 不可变标记,防 RUF012(可变默认值),语义也更准确。
    _SKIP_TAGS = frozenset({"script", "style", "noscript", "head", "title", "meta", "link"})

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

    HTML/纯文本直接抓取;PDF 走 Jina Reader(r.jina.ai,免费无 key,
    返回 Markdown 文本)。对应原项目 fetch 工具的 api 路径。

    SSRF:先经 netguard 解析并校验目标 IP,再以该 IP 直连(见模块头说明)。
    重定向逐跳手动跟随,每一跳都重新过 netguard——自动跟随会让攻击者用
    公网 302 跳转到内网地址绕过校验。
    """
    # scheme 在这里先做一次初筛(netguard 里也会查),同时供重定向循环判定
    split = urlsplit(url)
    if split.scheme not in ("http", "https"):
        raise ValueError(f"不支持的协议: {split.scheme or '(空)'}(仅允许 http/https)")

    # URL 以 .pdf 结尾或带 pdf 查询参数的,直接走 Jina(省一次无效的 HTML 抓取)
    if _looks_like_pdf(url):
        return await _fetch_via_jina(url)

    current_url = url
    # 手动跟随重定向(每跳重新校验);正常站点 5 跳足够
    for _ in range(6):
        ip, port = await resolve_safe_address(current_url)
        # 以校验过的 IP 建连(见 _get_bound),Host/SNI 仍传原域名
        async with httpx.AsyncClient(
            timeout=30,
            headers={"Accept": _ACCEPT_HEADER, "User-Agent": "Ryoshi/0.1 (+fetch)"},
        ) as client:
            resp = await _get_bound(client, current_url, ip, port)
        if resp.status_code in (301, 302, 303, 307, 308):
            location = resp.headers.get("location")
            if not location:
                break
            # 相对路径重定向:基于当前 URL 解析成绝对地址
            from urllib.parse import urljoin

            current_url = urljoin(current_url, location)
            continue
        break

    if resp.status_code != 200:
        raise ValueError(f"抓取失败: HTTP {resp.status_code}")

    content_type = (resp.headers.get("content-type") or "").lower()
    body = resp.text

    if "application/pdf" in content_type:
        # 响应头声明 PDF(但 URL 没带 .pdf 后缀的场景):改走 Jina
        return await _fetch_via_jina(current_url)

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

    return FetchResult(url=current_url, title=title, text=text)


def _looks_like_pdf(url: str) -> bool:
    """URL 形态初筛:.pdf 后缀(忽略查询串)或常见 PDF 站点参数。"""
    from urllib.parse import urlsplit as _us

    path = _us(url).path.lower()
    if path.endswith(".pdf"):
        return True
    return ".pdf" in _us(url).query.lower()


# Jina Reader:免费无 key,GET https://r.jina.ai/<url> 返回页面的 Markdown 文本。
# 目标是固定域名(非用户可控的代理目标),不构成 SSRF 面;
# 但 URL 本身仍先过 netguard(抓内网 PDF 同样被拒)。
_JINA_READER_BASE = "https://r.jina.ai/"


async def _fetch_via_jina(url: str) -> FetchResult:
    """经 Jina Reader 抓取 PDF(或 JS 渲染页)正文。

    Jina 不可达(部分网络环境到不了 r.jina.ai)时降级为本地
    pypdf 解析:自己下载 PDF 字节流(仍过 SSRF 校验直连)后抽文本。
    两条路都失败才抛 ValueError 给智能体。
    """
    # 目标 URL 仍需 SSRF 校验:Jina 会替我们抓,但内网地址不该经它转述
    await avalidate_outbound_url(url)

    from ryoshi.http import get_http_client

    try:
        resp = await get_http_client().get(
            f"{_JINA_READER_BASE}{url}",
            headers={"Accept": "text/plain", "User-Agent": "Ryoshi/0.1 (+fetch)"},
        )
        if resp.status_code == 200:
            text = resp.text
            # Jina 返回 Markdown,首个标题行可当 title
            title = ""
            for line in text.split("\n"):
                stripped = line.strip()
                if stripped.startswith("# "):
                    title = stripped[2:].strip()
                    break
            if len(text) > CONTENT_CHARACTER_LIMIT:
                text = text[:CONTENT_CHARACTER_LIMIT] + "...[truncated]"
            return FetchResult(url=url, title=title, text=text)
    except httpx.HTTPError:
        pass  # Jina 不可达 → 走本地兜底

    return await _fetch_pdf_local(url)


async def _fetch_pdf_local(url: str) -> FetchResult:
    """本地 PDF 解析兜底:下载字节流(校验过的 IP 直连)+ pypdf 抽文本。

    质量弱于 Jina(纯文本流,无排版结构),但在 r.jina.ai 不可达的
    网络环境仍能作答;PDF 里的扫描图(纯图片页)抽不出文本时如实报错。
    """
    ip, port = await resolve_safe_address(url)
    async with httpx.AsyncClient(
        timeout=60,  # PDF 可能较大
        headers={"User-Agent": "Ryoshi/0.1 (+fetch)"},
    ) as client:
        # 与 HTML 路径同样:手动跟重定向,每跳重新过 SSRF 校验
        current_url = url
        for _ in range(6):
            ip, port = await resolve_safe_address(current_url)
            resp = await _get_bound(client, current_url, ip, port)
            if resp.status_code in (301, 302, 303, 307, 308):
                location = resp.headers.get("location")
                if not location:
                    break
                from urllib.parse import urljoin

                current_url = urljoin(current_url, location)
                continue
            break
    if resp.status_code != 200:
        raise ValueError(f"PDF 下载失败: HTTP {resp.status_code}")

    import io

    from pypdf import PdfReader

    try:
        reader = PdfReader(io.BytesIO(resp.content))
        pages = [page.extract_text() or "" for page in reader.pages]
        text = "\n\n".join(p for p in pages if p.strip())
    except Exception as exc:
        raise ValueError(f"PDF 解析失败: {type(exc).__name__}") from exc

    if not text.strip():
        raise ValueError("PDF 中没有可提取的文本(可能是扫描件/纯图片 PDF)")

    title = ""
    try:
        meta_title = (reader.metadata or {}).get("/Title") if reader.metadata else None
        if meta_title:
            title = str(meta_title).strip()
    except Exception:
        pass
    if len(text) > CONTENT_CHARACTER_LIMIT:
        text = text[:CONTENT_CHARACTER_LIMIT] + "...[truncated]"
    return FetchResult(url=url, title=title, text=text)


async def _get_bound(
    client: httpx.AsyncClient, url: str, ip: str, port: int
) -> httpx.Response:
    """用校验过的 (ip, port) 直连目标,Host/SNI 仍用原域名。

    实现方式:把 URL 里的域名替换为已校验 IP 发起请求,同时:
      - Host 头显式设为原域名(虚拟主机路由/服务端校验依赖它)
      - SNI 用原域名(TLS 证书匹配依赖它,经 extensions 传递)
    这样"建立 TCP 连接的地址"就是 netguard 校验过的地址。
    """
    split = urlsplit(url)
    hostname = split.hostname or ip
    netloc = f"{ip}:{port}" if ":" not in ip else f"[{ip}]:{port}"
    bound_url = url.replace(f"{split.scheme}://{split.netloc}", f"{split.scheme}://{netloc}", 1)
    return await client.get(
        bound_url,
        headers={"Host": hostname},
        extensions={"sni_hostname": hostname},
    )
