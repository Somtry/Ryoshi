"""模型注册表:把 "providerId:modelId" 解析成可调用的 LangChain 聊天模型。

设计意图:
    对应原项目 lib/utils/registry.ts 的 getModel。原项目用 Vercel AI SDK
    的 provider 注册表;这里换成 LangChain 的各家 ChatModel。
    输入约定与原项目一致——"openai:gpt-5"、"anthropic:claude-..." 这样的
    带前缀字符串,按前缀分发到对应 provider 构造模型实例。

    哪个 provider 可用,取决于配置了哪些 API key(is_provider_enabled),
    与原项目的判断逻辑逐条对应。
"""

from langchain_core.language_models import BaseChatModel

from ryoshi.config import get_settings


class ModelConfigError(Exception):
    """模型配置错误(前缀未知,或对应 provider 未配置密钥)。"""


def is_provider_enabled(provider_id: str) -> bool:
    """判断某 provider 是否已配置可用(与原项目 isProviderEnabled 对应)。"""
    s = get_settings()
    return {
        "openai": bool(s.openai_api_key),
        "anthropic": bool(s.anthropic_api_key),
        "google": bool(s.google_generative_ai_api_key),
        # openai-compatible 与 ollama 需要额外的基础地址,阶段 4 再接入
        "openai-compatible": False,
        "ollama": False,
    }.get(provider_id, False)


def get_model(full_model: str) -> BaseChatModel:
    """把 "providerId:modelId" 解析成 LangChain 聊天模型。

    参数:
        full_model: 形如 "openai:gpt-5.6-luna"、"anthropic:claude-opus-4-8"
    返回:
        已配置好密钥、可直接 .bind_tools() / .astream() 的 ChatModel。
    """
    if ":" not in full_model:
        raise ModelConfigError(f"模型标识缺少 provider 前缀: {full_model!r}")
    provider_id, model_id = full_model.split(":", 1)

    if not is_provider_enabled(provider_id):
        raise ModelConfigError(f"provider 未启用(缺少密钥): {provider_id}")

    s = get_settings()
    if provider_id == "openai":
        from langchain_openai import ChatOpenAI

        return ChatOpenAI(model=model_id, api_key=s.openai_api_key)
    if provider_id == "anthropic":
        from langchain_anthropic import ChatAnthropic

        return ChatAnthropic(model=model_id, api_key=s.anthropic_api_key)
    if provider_id == "google":
        from langchain_google_genai import ChatGoogleGenerativeAI

        return ChatGoogleGenerativeAI(
            model=model_id, google_api_key=s.google_generative_ai_api_key
        )

    raise ModelConfigError(f"暂不支持的 provider: {provider_id}")


def default_model_id() -> str:
    """返回默认可用模型(Quick 模式起步用)。

    按已配置的密钥挑一个,优先级与原项目默认模型(OpenAI)一致。
    """
    s = get_settings()
    if s.openai_api_key:
        return "openai:gpt-4o-mini"
    if s.anthropic_api_key:
        return "anthropic:claude-haiku-4-5-20251001"
    if s.google_generative_ai_api_key:
        return "google:gemini-2.0-flash"
    raise ModelConfigError("未配置任何 AI 提供商密钥,无法选用默认模型")
