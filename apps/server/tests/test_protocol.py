"""协议实现的黄金测试。

设计意图:
    SSE 协议是前后端唯一不可随意更改的契约。这些测试把"线上字节的精确形态"
    固化下来——任何改动若导致输出字节变化,测试立即失败,从而在接入前端之前
    就拦住协议偏差。测试样本与 PROTOCOL.md 中的示例一一对应。
"""

import json

import pytest

from ryoshi.chat.frames import (
    Finish,
    SourceUrl,
    Start,
    TextDelta,
    TextEnd,
    TextStart,
    ToolInputAvailable,
    ToolOutputAvailable,
)
from ryoshi.chat.smoother import detect_chunk, smooth_text
from ryoshi.chat.sse import SSE_HEADERS, encode_done, encode_frame


class TestFrameSerialization:
    """帧 → SSE 字节的精确序列化。"""

    def test_text_delta_保留中文且不转义(self):
        out = encode_frame(TextDelta(id="t1", delta="你好"))
        assert out == 'data: {"type":"text-delta","id":"t1","delta":"你好"}\n\n'

    def test_tool_call_字段名为_camelCase(self):
        out = encode_frame(
            ToolInputAvailable(toolCallId="call_1", toolName="search", input={"query": "x"})
        )
        # snake_case 字段必须按 alias 输出为 camelCase
        assert '"toolCallId":"call_1"' in out
        assert '"toolName":"search"' in out
        assert "tool_call_id" not in out

    def test_可选字段为_none_则不出现(self):
        out = encode_frame(Start(messageId="m1"))
        # messageMetadata 为 None,应被剔除而非输出 null
        assert "messageMetadata" not in out
        assert '"messageId":"m1"' in out

    def test_source_url_序列化(self):
        out = encode_frame(SourceUrl(sourceId="s1", url="https://a.com", title="标题"))
        assert '"type":"source-url"' in out
        assert '"sourceId":"s1"' in out

    def test_done_终止标记(self):
        assert encode_done() == "data: [DONE]\n\n"

    def test_响应头逐字对齐(self):
        assert SSE_HEADERS["content-type"] == "text/event-stream"
        assert SSE_HEADERS["x-vercel-ai-ui-message-stream"] == "v1"
        assert SSE_HEADERS["x-accel-buffering"] == "no"

    def test_完整帧序列可还原(self):
        """一段典型序列应能被逐帧 JSON.parse 还原(模拟前端行为)。"""
        frames = [
            Start(messageId="m1"),
            TextStart(id="t1"),
            TextDelta(id="t1", delta="根据"),
            TextDelta(id="t1", delta="搜索结果"),
            TextEnd(id="t1"),
            ToolOutputAvailable(toolCallId="c1", output={"results": []}),
            Finish(finishReason="stop"),
        ]
        wire = "".join(encode_frame(f) for f in frames) + encode_done()
        # 按 SSE 空行分隔拆出每个 data: 载荷
        events = [e for e in wire.split("\n\n") if e]
        assert events[-1] == "data: [DONE]"
        parsed = [json.loads(e[len("data: "):]) for e in events[:-1]]
        assert [p["type"] for p in parsed] == [
            "start",
            "text-start",
            "text-delta",
            "text-delta",
            "text-end",
            "tool-output-available",
            "finish",
        ]


class TestSmoother:
    """smoothStream 按词平滑行为。"""

    def test_detect_chunk_切出首个词(self):
        assert detect_chunk("hello world foo") == "hello "

    def test_detect_chunk_无空白则不出词(self):
        # 单个词没有尾随空白,不构成完整"词片"
        assert detect_chunk("hello") is None

    def test_detect_chunk_空缓冲区(self):
        assert detect_chunk("") is None

    def test_detect_chunk_保留词前内容(self):
        # 对应 AI SDK 的 slice(0, match.index) + match[0]
        assert detect_chunk("  hi there") == "  hi "

    @pytest.mark.asyncio
    async def test_smooth_text_按词切分(self):
        async def source():
            yield "hello world"
            yield " again"

        pieces = [p async for p in smooth_text(source(), delay_ms=0)]
        # 缓冲区合并 "hello world again",切出 "hello "、"world ",尾部 "again" 冲刷
        assert pieces == ["hello ", "world ", "again"]

    @pytest.mark.asyncio
    async def test_smooth_text_尾部无空白也冲刷(self):
        async def source():
            yield "end"

        pieces = [p async for p in smooth_text(source(), delay_ms=0)]
        assert pieces == ["end"]

    @pytest.mark.asyncio
    async def test_smooth_text_中文行为与原站一致(self):
        # 中文无空格分词,整句会作为一个尾巴在结尾冲刷(与原项目同一正则的表现)
        async def source():
            yield "你好世界"

        pieces = [p async for p in smooth_text(source(), delay_ms=0)]
        assert pieces == ["你好世界"]
