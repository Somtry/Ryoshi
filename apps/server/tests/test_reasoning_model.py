"""ReasoningCapableChatOpenAI 的 reasoning_content 保留测试。

设计意图:
    langchain-openai 1.6.0 的 _convert_delta_to_message_chunk 会把
    DeepSeek-R1 流式 delta 里的 reasoning_content 静默丢弃(只取
    content/function_call/tool_calls)。本子类在转换后把它补回
    additional_kwargs——这是思考链整条链路的源头,必须锁定。
"""

from langchain_core.messages import AIMessageChunk

from ryoshi.agents.models import ReasoningCapableChatOpenAI


def _deepseek_chunk(reasoning: str | None = None, content: str | None = None):
    """构造 ChatOpenAI 内部 _convert_chunk_to_generation_chunk 期望的 chunk dict
    (openai SDK 解析前的原始 JSON dict 形态,DeepSeek 会带 reasoning_content)。"""
    delta: dict = {}
    if reasoning is not None:
        delta["reasoning_content"] = reasoning
    if content is not None:
        delta["content"] = content
    return {
        "id": "chatcmpl-1",
        "object": "chat.completion.chunk",
        "created": 1,
        "model": "deepseek-reasoner",
        "choices": [{"index": 0, "delta": delta, "finish_reason": None}],
    }


def _make_model() -> ReasoningCapableChatOpenAI:
    return ReasoningCapableChatOpenAI(model="deepseek-reasoner", api_key="sk-test")


class TestReasoningExtraction:
    def test_思考delta_进入_additional_kwargs(self):
        model = _make_model()
        gen = model._convert_chunk_to_generation_chunk(
            _deepseek_chunk(reasoning="思考中..."), AIMessageChunk, None
        )
        assert gen is not None
        assert gen.message.additional_kwargs.get("reasoning_content") == "思考中..."
        # 正文 content 不受影响
        assert gen.message.content == ""

    def test_正文delta_不带reasoning_不受影响(self):
        model = _make_model()
        gen = model._convert_chunk_to_generation_chunk(
            _deepseek_chunk(content="答案"), AIMessageChunk, None
        )
        assert gen is not None
        assert gen.message.content == "答案"
        assert "reasoning_content" not in gen.message.additional_kwargs

    def test_多个思考delta_按序拼接(self):
        model = _make_model()
        g1 = model._convert_chunk_to_generation_chunk(
            _deepseek_chunk(reasoning="第一段 "), AIMessageChunk, None
        )
        g2 = model._convert_chunk_to_generation_chunk(
            _deepseek_chunk(reasoning="第二段"), AIMessageChunk, None
        )
        # 每个块独立携带自己的增量(流式语义)
        assert g1.message.additional_kwargs["reasoning_content"] == "第一段 "
        assert g2.message.additional_kwargs["reasoning_content"] == "第二段"

    def test_无choices的chunk_不崩(self):
        model = _make_model()
        gen = model._convert_chunk_to_generation_chunk(
            {"id": "x", "object": "chat.completion.chunk", "choices": []},
            AIMessageChunk,
            None,
        )
        # 空 choices 是合法心跳/用量块,返回空 generation 而非报错
        assert gen is not None
