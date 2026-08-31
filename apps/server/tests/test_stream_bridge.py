"""智能体事件流 → SSE 帧流 桥接的测试。

设计意图:
    agent_stream_to_frames 是"Python 后端 ↔ 不动的前端"之间的关键适配层,
    但它依赖真实模型才能跑。这里用一个假的 astream_events 事件源,
    验证桥接逻辑能把 LangChain 事件正确翻成 UIMessageStream 帧序列——
    无需 API key 即可锁定这层的行为。
"""

from ryoshi.chat.frames import (
    Finish,
    Start,
    TextDelta,
    TextEnd,
    TextStart,
    ToolInputAvailable,
    ToolInputStart,
    ToolOutputAvailable,
)
from ryoshi.chat.stream import agent_stream_to_frames


class _Chunk:
    def __init__(self, content):
        self.content = content


class FakeAgent:
    """模拟 LangGraph astream_events 的事件序列:一段文本 + 一次工具调用。"""

    async def astream_events(self, payload, version, config):
        yield {"event": "on_chat_model_stream", "data": {"chunk": _Chunk("你好 ")}}
        yield {"event": "on_chat_model_stream", "data": {"chunk": _Chunk("世界")}}
        yield {
            "event": "on_tool_start",
            "run_id": "call_1",
            "name": "search",
            "data": {"input": {"query": "测试"}},
        }
        yield {
            "event": "on_tool_end",
            "run_id": "call_1",
            "data": {"output": {"results": []}},
        }
        yield {"event": "on_chat_model_stream", "data": {"chunk": _Chunk("回答。 ")}}


async def test_桥接产出正确的帧序列():
    frames = [
        f
        async for f in agent_stream_to_frames(
            FakeAgent(), messages=[], message_id="m1", message_metadata={"searchMode": "quick"}
        )
    ]

    types = [type(f) for f in frames]
    # 首帧 start,末帧 finish
    assert isinstance(frames[0], Start)
    assert isinstance(frames[-1], Finish)
    # 文本段: text-start → text-delta* → text-end(在工具调用前闭合)
    assert TextStart in types
    assert TextDelta in types
    assert TextEnd in types
    # 工具段: input-start → input-available → output-available
    assert ToolInputStart in types
    assert ToolInputAvailable in types
    assert ToolOutputAvailable in types


async def test_文本帧的_delta_被平滑切分():
    frames = [
        f
        async for f in agent_stream_to_frames(FakeAgent(), messages=[], message_id="m1")
    ]
    deltas = [f.delta for f in frames if isinstance(f, TextDelta)]
    # "你好 世界" 与 "回答。 " 应被 smoothStream 按词切出(词+空白)
    assert any(d.endswith(" ") for d in deltas), f"预期有按词切出的增量: {deltas}"


async def test_工具事件携带正确的_id_与名称():
    frames = [
        f
        async for f in agent_stream_to_frames(FakeAgent(), messages=[], message_id="m1")
    ]
    start = next(f for f in frames if isinstance(f, ToolInputStart))
    out = next(f for f in frames if isinstance(f, ToolOutputAvailable))
    assert start.tool_name == "search"
    assert out.tool_call_id == "call_1"
