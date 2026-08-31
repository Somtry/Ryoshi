"""SSE 线格式序列化。

设计意图:
    把一帧(Pydantic 模型)编码成 SSE 线上字节。格式严格对齐 AI SDK v7 的
    JsonToSseTransformStream:
      每帧:  "data: " + JSON + "\\n\\n"
      结束:  "data: [DONE]\\n\\n"

    JSON 序列化用 ensure_ascii=False 保留中文原文(AI SDK 的 JSON.stringify
    也不转义非 ASCII),并剔除 None 字段以匹配"可选字段缺省即不出现"。
"""

import json
from typing import Any

from ryoshi.chat.frames import _Frame

# SSE 事件分隔:帧与帧之间靠空行分隔
_EVENT_SUFFIX = "\n\n"


def encode_frame(frame: _Frame | dict[str, Any]) -> str:
    """把一帧编码为一行 SSE 事件(带结尾空行)。

    接受帧模型或已序列化的 dict。返回形如:
        data: {"type":"text-delta","id":"t1","delta":"你好"}\n\n
    """
    payload = frame.to_json_dict() if isinstance(frame, _Frame) else frame
    body = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    return f"data: {body}{_EVENT_SUFFIX}"


def encode_done() -> str:
    """流终止标记。前端据此知道本条消息推送完毕。"""
    return f"data: [DONE]{_EVENT_SUFFIX}"


# 响应头:与 AI SDK v7 的 UI_MESSAGE_STREAM_HEADERS 逐字一致。
# x-accel-buffering: no 是为了关掉 nginx 的响应缓冲,否则流式会被攒成批次。
SSE_HEADERS: dict[str, str] = {
    "content-type": "text/event-stream",
    "cache-control": "no-cache",
    "connection": "keep-alive",
    "x-vercel-ai-ui-message-stream": "v1",
    "x-accel-buffering": "no",
}
