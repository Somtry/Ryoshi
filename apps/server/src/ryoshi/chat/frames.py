"""UIMessageStream 消息帧(Pydantic 模型)。

设计意图:
    这是 packages/protocol/PROTOCOL.md 的代码化——后端产出的每一帧 SSE
    都必须符合这里的结构。用 Pydantic 建模的好处:
      1. 构造帧时即校验字段,避免手抖写错 key 导致前端静默渲染失败
      2. model_dump(by_alias=True, exclude_none=True) 直接得到线上 JSON
         (exclude_none 对应 AI SDK 里"可选字段缺省就不出现"的行为)

    帧的判别字段是 type;每种帧一个模型类,字段名与 AI SDK v7 完全一致
    (Python 侧用 snake_case + alias 映射到 camelCase)。
"""

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class _Frame(BaseModel):
    """所有帧的基类:序列化时按 alias 输出 camelCase,且忽略 None 字段。"""

    model_config = ConfigDict(populate_by_name=True)

    def to_json_dict(self) -> dict[str, Any]:
        """转成线上 JSON 形态(camelCase、剔除 None)。"""
        return self.model_dump(by_alias=True, exclude_none=True)


# ---- 文本 ----
class TextStart(_Frame):
    type: Literal["text-start"] = "text-start"
    id: str


class TextDelta(_Frame):
    type: Literal["text-delta"] = "text-delta"
    id: str
    delta: str


class TextEnd(_Frame):
    type: Literal["text-end"] = "text-end"
    id: str


# ---- 推理过程 ----
class ReasoningStart(_Frame):
    type: Literal["reasoning-start"] = "reasoning-start"
    id: str


class ReasoningDelta(_Frame):
    type: Literal["reasoning-delta"] = "reasoning-delta"
    id: str
    delta: str


class ReasoningEnd(_Frame):
    type: Literal["reasoning-end"] = "reasoning-end"
    id: str


# ---- 工具调用 ----
class ToolInputStart(_Frame):
    type: Literal["tool-input-start"] = "tool-input-start"
    tool_call_id: str = Field(alias="toolCallId")
    tool_name: str = Field(alias="toolName")


class ToolInputAvailable(_Frame):
    type: Literal["tool-input-available"] = "tool-input-available"
    tool_call_id: str = Field(alias="toolCallId")
    tool_name: str = Field(alias="toolName")
    input: Any


class ToolOutputAvailable(_Frame):
    type: Literal["tool-output-available"] = "tool-output-available"
    tool_call_id: str = Field(alias="toolCallId")
    output: Any


class ToolOutputError(_Frame):
    type: Literal["tool-output-error"] = "tool-output-error"
    tool_call_id: str = Field(alias="toolCallId")
    error_text: str = Field(alias="errorText")


# ---- 来源引用 ----
class SourceUrl(_Frame):
    type: Literal["source-url"] = "source-url"
    source_id: str = Field(alias="sourceId")
    url: str
    title: str | None = None


class SourceDocument(_Frame):
    type: Literal["source-document"] = "source-document"
    source_id: str = Field(alias="sourceId")
    media_type: str = Field(alias="mediaType")
    title: str
    filename: str | None = None


# ---- 文件 ----
class FilePart(_Frame):
    type: Literal["file"] = "file"
    url: str
    media_type: str = Field(alias="mediaType")


# ---- 自定义数据部件(Generative UI 之外的 data-*)----
class DataPart(_Frame):
    """data-${name} 帧。type 需以 'data-' 开头。"""

    type: str
    id: str | None = None
    data: Any
    transient: bool | None = None


# ---- 流控制 ----
class Start(_Frame):
    type: Literal["start"] = "start"
    message_id: str | None = Field(default=None, alias="messageId")
    message_metadata: dict[str, Any] | None = Field(default=None, alias="messageMetadata")


class StartStep(_Frame):
    type: Literal["start-step"] = "start-step"


class FinishStep(_Frame):
    type: Literal["finish-step"] = "finish-step"


class Finish(_Frame):
    type: Literal["finish"] = "finish"
    finish_reason: str | None = Field(default=None, alias="finishReason")
    message_metadata: dict[str, Any] | None = Field(default=None, alias="messageMetadata")


class Abort(_Frame):
    type: Literal["abort"] = "abort"
    reason: str | None = None


class Error(_Frame):
    type: Literal["error"] = "error"
    error_text: str = Field(alias="errorText")


class MessageMetadata(_Frame):
    type: Literal["message-metadata"] = "message-metadata"
    message_metadata: dict[str, Any] = Field(alias="messageMetadata")
