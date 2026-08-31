"""智能体事件流 → UIMessageStream 帧流 的桥接。

设计意图:
    LangGraph 的 astream_events 吐的是 LangChain 体系的事件
    (on_chat_model_stream / on_tool_start / on_tool_end 等),
    而前端只认 AI SDK 的 UIMessageStream 帧(text-delta / tool-input-* 等)。
    本模块做这层翻译:
      模型流式文本   → text-start / text-delta / text-end
      工具调用开始   → tool-input-start
      工具入参就绪   → tool-input-available
      工具返回       → tool-output-available
    文本增量再过一遍 smoothStream 平滑,最终由 sse.py 编码上线。

    这层桥接是"后端换成 Python 而前端不动"的关键适配点。
"""

import json
import uuid
from collections.abc import AsyncIterator
from typing import Any

from ryoshi.chat.frames import (
    Finish,
    Start,
    TextDelta,
    TextEnd,
    TextStart,
    ToolInputAvailable,
    ToolInputStart,
    ToolOutputAvailable,
    _Frame,
)
from ryoshi.chat.smoother import smooth_text


def _new_id() -> str:
    return uuid.uuid4().hex[:12]


async def agent_stream_to_frames(
    agent: Any,
    messages: list,
    message_id: str | None = None,
    message_metadata: dict | None = None,
    on_assistant_message: Any = None,
) -> AsyncIterator[_Frame]:
    """驱动智能体并把其事件翻译为 UIMessageStream 帧。

    参数:
        agent: create_react_agent 编译出的 LangGraph 智能体
        messages: 初始消息列表(LangChain 消息)
        message_id: 本次 assistant 回答的消息 id,写入首帧 start。
            关键约束:必须是 assistant 消息自己的新 id,绝不能复用
            用户消息的 id——前端 useChat 会把 start.messageId 赋给正在
            流式的 assistant 消息;若与 user 消息同 id,前端会判定为
            "替换最后一条"而把用户消息覆盖掉,导致用户消息从界面消失。
            缺省时由后端生成一个。
        message_metadata: 写入首帧 start,供前端关联追踪
        on_assistant_message: 可选回调。流正常结束时,以收集到的完整
            assistant 消息(id/role/parts)调用之,供路由层持久化。
    产出:
        按序的帧(start → 若干 step → finish)。
    """
    assistant_message_id = message_id or _new_id()
    yield Start(messageId=assistant_message_id, messageMetadata=message_metadata)

    # 文本块 id:同一轮连续文本共用一个 id,模型开始新一轮文本时换新的
    current_text_id: str | None = None
    text_open = False

    # 收集 assistant 消息的部件(供持久化)。顺序即 parts.order:
    # 文本段与工具部件按事件发生的真实先后追加,保持与渲染顺序一致。
    collected_parts: list[dict] = []
    # 工具调用按 toolCallId 索引到 collected_parts 里的位置,
    # 便于 on_tool_end 时把 output 回填进同一个部件。
    tool_part_index: dict[str, int] = {}
    # 当前文本段的累积内容(text-delta 是增量,落库要完整文本)
    text_buffer: list[str] = []

    async def raw_text_deltas(stream) -> AsyncIterator[str]:
        nonlocal current_text_id, text_open
        async for event in stream:
            kind = event.get("event")
            if kind == "on_chat_model_stream":
                chunk = event.get("data", {}).get("chunk")
                text = getattr(chunk, "content", None)
                # content 可能是 str 或分块列表;统一抽成文本
                if isinstance(text, list):
                    text = "".join(
                        seg.get("text", "") if isinstance(seg, dict) else str(seg) for seg in text
                    )
                if text:
                    yield text

    try:
        stream = agent.astream_events(
            {"messages": messages}, version="v2", config={"recursion_limit": 20}
        )

        # 我们需要同时看到"模型文本流"与"工具事件",因此不能只用 raw_text_deltas,
        # 而是直接遍历事件流,按类型分流。
        async for event in stream:
            kind = event.get("event")

            if kind == "on_chat_model_stream":
                chunk = event.get("data", {}).get("chunk")
                text = getattr(chunk, "content", None)
                if isinstance(text, list):
                    text = "".join(
                        seg.get("text", "") if isinstance(seg, dict) else str(seg) for seg in text
                    )
                if not text:
                    continue
                if not text_open:
                    current_text_id = _new_id()
                    text_buffer = []  # 新一轮文本开始,清空缓冲
                    yield TextStart(id=current_text_id)
                    text_open = True
                text_buffer.append(text)
                # 文本增量经 smoothStream 平滑后再发
                async def _single():
                    yield text
                async for piece in smooth_text(_single()):
                    yield TextDelta(id=current_text_id or _new_id(), delta=piece)

            elif kind == "on_tool_start":
                if text_open:
                    # 文本段闭合:把累积的完整文本作为一个 text 部件落库
                    collected_parts.append({"type": "text", "text": "".join(text_buffer)})
                    yield TextEnd(id=current_text_id or _new_id())
                    text_open = False
                tool_call_id = event.get("run_id") or _new_id()
                tool_name = event.get("name", "tool")
                tool_input = event.get("data", {}).get("input")
                # 工具部件追加到当前位置,记录索引供 output 回填
                tool_part_index[tool_call_id] = len(collected_parts)
                collected_parts.append(
                    {
                        "type": f"tool-{tool_name}",
                        "toolCallId": tool_call_id,
                        "state": "input-available",
                        "input": tool_input,
                    }
                )
                yield ToolInputStart(toolCallId=tool_call_id, toolName=tool_name)
                yield ToolInputAvailable(
                    toolCallId=tool_call_id, toolName=tool_name, input=tool_input
                )

            elif kind == "on_tool_end":
                tool_call_id = event.get("run_id") or _new_id()
                output = event.get("data", {}).get("output")
                # LangChain 工具输出常包一层 ToolMessage;取其 content
                output_payload = getattr(output, "content", output)
                if isinstance(output_payload, str):
                    try:
                        output_payload = json.loads(output_payload)
                    except (ValueError, TypeError):
                        pass
                # 把 output 回填进对应工具部件,标记为 output-available
                idx = tool_part_index.get(tool_call_id)
                if idx is not None:
                    collected_parts[idx]["output"] = output_payload
                    collected_parts[idx]["state"] = "output-available"
                yield ToolOutputAvailable(toolCallId=tool_call_id, output=output_payload)

        if text_open:
            collected_parts.append({"type": "text", "text": "".join(text_buffer)})
            yield TextEnd(id=current_text_id or _new_id())
        yield Finish(finishReason="stop")

        # 流正常结束:组装完整 assistant 消息并回调(供路由层持久化)。
        if on_assistant_message is not None:
            await on_assistant_message(
                {
                    "id": assistant_message_id,
                    "role": "assistant",
                    "parts": collected_parts,
                    "metadata": message_metadata,
                }
            )

    except Exception as exc:  # noqa: BLE001 —— 流出错以 error 帧收尾,不抛出中断连接
        if text_open:
            yield TextEnd(id=current_text_id or _new_id())
        from ryoshi.chat.frames import Error

        yield Error(errorText=str(exc))
