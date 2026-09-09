"""上下文窗口截断:消息列表 token 估算与截断。

设计意图:
    对应原项目 lib/utils/context-window.ts。当对话历史过长超出模型上下文窗口时,
    按"保首条用户消息 + 尽量保留最新消息"的策略截断,确保模型能正常推理。

    token 估算:优先用 tiktoken(cl100k_base,与 GPT-4 一致);未安装或失败时
    退化为"4 字符 ≈ 1 token"的粗略估计。附件按 mediaType 单独估算。
"""

from __future__ import annotations

from typing import Any

# ---- 模型上下文窗口配置(与原项目 MODEL_CONTEXT_WINDOWS 对应)----
# 前缀匹配:按最长前缀命中(BYOK 自定义 id 如 gpt-5.2-mini 不必逐一登记)。
# 清单覆盖常见模型;未知模型走 DEFAULT(见下)。
MODEL_CONTEXT_WINDOWS: dict[str, dict[str, int]] = {
    # DeepSeek(OpenAI 兼容端点;V3/R1 系列 128k)
    "deepseek": {"contextWindow": 128000, "outputTokens": 16384},
    # OpenAI(GPT-4o/4.1/5 系均为 128k+ 输入;输出上限 16k~32k)
    "gpt-4o": {"contextWindow": 128000, "outputTokens": 16384},
    "gpt-4.1": {"contextWindow": 1047576, "outputTokens": 32768},
    "gpt-4-turbo": {"contextWindow": 128000, "outputTokens": 4096},
    "gpt-5": {"contextWindow": 400000, "outputTokens": 32768},
    "o1": {"contextWindow": 200000, "outputTokens": 32768},
    "o3": {"contextWindow": 200000, "outputTokens": 100000},
    "o4": {"contextWindow": 200000, "outputTokens": 100000},
    # Anthropic(Claude 3.5 起 200k;4 系 sonnet 1M 可选、默认 200k)
    "claude-3": {"contextWindow": 200000, "outputTokens": 8192},
    "claude-4": {"contextWindow": 200000, "outputTokens": 16384},
    "claude-opus": {"contextWindow": 200000, "outputTokens": 16384},
    "claude-sonnet": {"contextWindow": 200000, "outputTokens": 16384},
    "claude-haiku": {"contextWindow": 200000, "outputTokens": 8192},
    # Google(Gemini 1.5/2.x 全系 1M)
    "gemini": {"contextWindow": 1048576, "outputTokens": 65536},
    # Qwen(开源系常见;qwen2.5/qwen3 128k)
    "qwen": {"contextWindow": 128000, "outputTokens": 8192},
    # GLM
    "glm": {"contextWindow": 128000, "outputTokens": 8192},
    # Kimi(Moonshot;长上下文是卖点)
    "moonshot": {"contextWindow": 128000, "outputTokens": 8192},
    "kimi": {"contextWindow": 128000, "outputTokens": 8192},
}

# 未知模型的默认窗口:2026 年在售模型几乎都是 128k 起步,旧默认 16k
# 会把长对话过早截断(用户明明还有余量却丢了上下文)。128k 是安全下限
# ——即使真实窗口更小,超限错误由 provider 返回,比静默截断可诊断。
DEFAULT_CONTEXT_WINDOW = 128000
DEFAULT_OUTPUT_TOKENS = 8192
# 安全缓冲:预留给 system prompt 与格式化开销
SAFETY_BUFFER_RATIO = 0.1

# tiktoken 编码缓存
_ENCODER_CACHE: dict[str, Any] = {}


def _get_encoder(model_id: str):
    """取 tiktoken 编码器。统一用 cl100k_base(GPT-4 系;Claude/Gemini 近似)。"""
    try:
        import tiktoken
    except ImportError:
        return None
    if "cl100k_base" not in _ENCODER_CACHE:
        try:
            _ENCODER_CACHE["cl100k_base"] = tiktoken.get_encoding("cl100k_base")
        except Exception:
            return None
    return _ENCODER_CACHE["cl100k_base"]


def _lookup_window(model_id: str) -> dict[str, int]:
    """查模型的窗口配置:精确命中 → 最长前缀命中 → 默认值。

    前缀匹配让 BYOK 自定义 id(gpt-5.2-mini、claude-sonnet-4-6 等)
    不必逐一登记也能拿到正确量级;多个前缀都命中时取更长者
    (如 "gpt-4o-mini" 同时命中 "gpt-4o" 与更泛的 "gpt-",取具体的)。
    """
    if model_id in MODEL_CONTEXT_WINDOWS:
        return MODEL_CONTEXT_WINDOWS[model_id]
    name = model_id.lower()
    best: dict[str, int] | None = None
    best_len = -1
    for prefix, info in MODEL_CONTEXT_WINDOWS.items():
        if name.startswith(prefix) and len(prefix) > best_len:
            best = info
            best_len = len(prefix)
    if best is not None:
        return best
    return {
        "contextWindow": DEFAULT_CONTEXT_WINDOW,
        "outputTokens": DEFAULT_OUTPUT_TOKENS,
    }


def get_max_allowed_tokens(model_id: str) -> int:
    """计算某模型允许的最大输入 token 数(上下文窗口 - 输出预留 - 安全缓冲)。"""
    info = _lookup_window(model_id)
    available = info["contextWindow"] - info["outputTokens"]
    available -= int(info["contextWindow"] * SAFETY_BUFFER_RATIO)
    return max(available, 1000)


def _extract_text(content: Any) -> str:
    """从消息 content 里抽纯文本(str 或 parts 列表)。"""
    if not content:
        return ""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return " ".join(p.get("text", "") for p in content if isinstance(p, dict) and "text" in p)
    return ""


def estimate_token_count(content: Any, model_id: str | None = None) -> int:
    """估算一条消息的 token 数。tiktoken 优先,失败退化为粗略估计。"""
    text = _extract_text(content)
    if not text:
        return 0

    if model_id:
        encoder = _get_encoder(model_id)
        if encoder:
            try:
                return len(encoder.encode(text)) + 4  # 4 = 消息格式化开销
            except Exception:
                pass

    # 退化:约 4 字符 = 1 token(英文;中文会偏多,可接受)
    return len(text) // 4 + 4


def truncate_messages(
    messages: list[Any], max_tokens: int, model_id: str | None = None
) -> list[Any]:
    """按 token 上限截断消息列表。

    策略(与原项目 truncateMessages 一致):
      1. 总 token 未超限时原样返回
      2. 保第一条用户消息(若其占比 < 30%)
      3. 从末尾往前尽量多保留最新消息
      4. 确保结果以用户消息开头(去掉孤立的 assistant 消息)
    """
    if not messages:
        return []
    if max_tokens <= 0:
        return []

    # LangChain 消息用 .type("human"/"ai"),dict 用 .role("user"/"assistant");统一归一
    def _role(m: Any) -> str:
        r = getattr(m, "role", None) or (m.get("role") if isinstance(m, dict) else None)
        if r:
            return r
        t = getattr(m, "type", None) or (m.get("type") if isinstance(m, dict) else None)
        return {"human": "user", "ai": "assistant"}.get(t, t or "")

    # 找第一条用户消息
    first_user_idx = next((i for i, m in enumerate(messages) if _role(m) == "user"), None)
    first_user_msg = messages[first_user_idx] if first_user_idx is not None else None

    # 计算每条消息的 token 数
    counts = [estimate_token_count(getattr(m, "content", None) or (m.get("content") if isinstance(m, dict) else ""), model_id) for m in messages]
    total = sum(counts)
    if total <= max_tokens:
        return messages

    result: list[Any] = []
    used = 0

    # 预留第一条用户消息
    if first_user_msg is not None and first_user_idx is not None:
        first_tokens = counts[first_user_idx]
        if first_tokens < max_tokens * 0.3:
            result.append(first_user_msg)
            used += first_tokens

    # 从末尾往前加
    recent: list[Any] = []
    for i in range(len(messages) - 1, -1, -1):
        if first_user_idx is not None and i == first_user_idx:
            continue
        tokens = counts[i]
        if used + tokens <= max_tokens:
            recent.insert(0, messages[i])
            used += tokens
        else:
            break

    result.extend(recent)

    # 确保以用户消息开头
    while result and _role(result[0]) != "user":
        result.pop(0)

    return result
