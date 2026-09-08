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


class TestAbortPersistence:
    """客户端断开时,部分回答应通过 stream_handle 暴露给路由层兜底持久化。"""

    class SlowAgent:
        """吐两个字就永久挂起(模拟模型慢/长工具执行)。"""

        class _Chunk:
            def __init__(self, content):
                self.content = content

        async def astream_events(self, payload, version, config):
            yield {"event": "on_chat_model_stream", "data": {"chunk": self._Chunk("回答第一段 ")}}
            # 模拟客户端在此时断开:这个 yield 之后流被 aclose
            await asyncio.sleep(3600)

    async def test_断开时_handle_里有部分消息快照(self):
        import asyncio

        from ryoshi.chat.stream import agent_stream_to_frames

        persisted_messages = []

        async def on_persist(msg):
            persisted_messages.append(msg)

        handle = {}
        frames = agent_stream_to_frames(
            TestAbortPersistence.SlowAgent(),
            messages=[],
            message_metadata={"searchMode": "quick"},
            on_assistant_message=on_persist,
            stream_handle=handle,
        )
        # 消费到 step-start 之后的文本增量,然后立即关闭(等价于客户端断开)
        got = []
        try:
            async for frame in frames:
                got.append(frame)
                # 拿到第一个文本增量(说明 step-start 已产出)后断开
                if type(frame).__name__ == "TextDelta":
                    break
        finally:
            await frames.aclose()

        # handle 里应有:部分消息快照(含已产出的部件)+ 未持久化标记
        partial = handle.get("partial_message")
        assert partial is not None
        assert partial["metadata"]["finishReason"] == "aborted"
        assert handle.get("persisted") is False
        # parts 至少包含 step-start
        types = [p.get("type") for p in partial["parts"]]
        assert "step-start" in types
        # 正常路径的 on_assistant_message 没被调用(流没走到头)
        assert persisted_messages == []

    async def test_正常结束_标记已持久化_handle_快照不触发兜底(self):
        from ryoshi.chat.stream import agent_stream_to_frames

        persisted_messages = []

        async def on_persist(msg):
            persisted_messages.append(msg)

        handle = {}
        frames = agent_stream_to_frames(
            FakeAgent(),
            messages=[],
            on_assistant_message=on_persist,
            stream_handle=handle,
        )
        async for _ in frames:
            pass

        assert handle.get("persisted") is True
        assert len(persisted_messages) == 1  # 恰好持久化一次
        # 路由层兜底条件(persisted=True)不满足 → 不会双写
