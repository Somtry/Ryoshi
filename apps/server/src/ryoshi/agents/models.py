"""模型注册表:把 "providerId:modelId" 解析成可调用的 LangChain 聊天模型。

设计意图:
    对应原项目 lib/utils/registry.ts 的 getModel。原项目用 Vercel AI SDK
    的 provider 注册表;这里换成 LangChain 的各家 ChatModel。
    输入约定与原项目一致——"openai:gpt-5"、"anthropic:claude-..." 这样的
    带前缀字符串,按前缀分发到对应 provider 构造模型实例。

    BYOK 改造:
      判定 provider 是否可用的口径分两层(用户密钥优先,环境变量兜底):
        1. 传了 user_id 且该用户在 user_api_keys 表里有 enabled=true 的对应行
           → 用用户自己的密钥(解密后)构造模型
        2. 否则回退到全局环境变量(匿名模式、未配密钥用户的兜底)

      入口分两组:
        - 异步: ais_provider_enabled / aget_model / adefault_model_id
          (路由、智能体里用——它们都在异步上下文)
        - 同步: is_provider_enabled / get_model / default_model_id
          (旧调用点保留;只能看环境变量,看不到用户密钥)
"""

from dataclasses import dataclass

from langchain_core.language_models import BaseChatModel

from ryoshi.config import get_settings

# ChatOpenAI 基类惰性导入(见 _build_model;这里只做类型引用)
try:  # pragma: no cover - 导入失败仅在未装 langchain-openai 的环境
    from langchain_openai import ChatOpenAI as _OpenAIModelBase
except ImportError:  # pragma: no cover
    _OpenAIModelBase = object  # type: ignore[assignment,misc]

#: 支持的 BYOK provider 列表(顺序即前端设置页的展示顺序)
BYOK_PROVIDERS = ("openai", "anthropic", "google", "deepseek", "openai-compatible")


class ModelConfigError(Exception):
    """模型配置错误(前缀未知,或对应 provider 未配置密钥)。"""


@dataclass(frozen=True)
class ProviderCredentials:
    """某 provider 的实际接入凭据(已确定来源:用户密钥 or 环境变量)。"""

    api_key: str
    base_url: str = ""
    models: str = ""  # 逗号分隔(openai-compatible 用)
    provider_name: str = ""  # 显示名(openai-compatible 用)
    source: str = "env"  # "user" 或 "env"


# ---------------------------------------------------------------------------
# 同步路径(仅环境变量)——保留给启动期/无 DB 上下文的旧调用点
# ---------------------------------------------------------------------------


def is_provider_enabled(provider_id: str) -> bool:
    """判断某 provider 是否已配置可用(仅看全局环境变量)。

    与原项目 isProviderEnabled 对应。BYOK 后,路由/智能体应改用
    ais_provider_enabled(user_id)——本函数只用于无 DB 上下文的场景。
    """
    s = get_settings()
    return {
        "openai": bool(s.openai_api_key),
        "anthropic": bool(s.anthropic_api_key),
        "google": bool(s.google_generative_ai_api_key),
        "deepseek": bool(s.deepseek_api_key),
        # 通用 openai-compatible:key 与 base_url 都配上才可用
        "openai-compatible": bool(
            s.openai_compatible_api_key and s.openai_compatible_api_base_url
        ),
        "ollama": False,
    }.get(provider_id, False)


def _env_credentials(provider_id: str) -> ProviderCredentials | None:
    """从环境变量取 provider 凭据。未配置返回 None。"""
    s = get_settings()
    if provider_id == "openai" and s.openai_api_key:
        return ProviderCredentials(api_key=s.openai_api_key)
    if provider_id == "anthropic" and s.anthropic_api_key:
        return ProviderCredentials(api_key=s.anthropic_api_key)
    if provider_id == "google" and s.google_generative_ai_api_key:
        return ProviderCredentials(api_key=s.google_generative_ai_api_key)
    if provider_id == "deepseek" and s.deepseek_api_key:
        return ProviderCredentials(
            api_key=s.deepseek_api_key, base_url=s.deepseek_base_url
        )
    if (
        provider_id == "openai-compatible"
        and s.openai_compatible_api_key
        and s.openai_compatible_api_base_url
    ):
        return ProviderCredentials(
            api_key=s.openai_compatible_api_key,
            base_url=s.openai_compatible_api_base_url,
            models=s.openai_compatible_models,
            provider_name=s.openai_compatible_provider_name or "OpenAI Compatible",
        )
    return None


def get_model(full_model: str) -> BaseChatModel:
    """同步版 get_model(仅环境变量)。新代码请用 aget_model。"""
    if ":" not in full_model:
        raise ModelConfigError(f"模型标识缺少 provider 前缀: {full_model!r}")
    provider_id, model_id = full_model.split(":", 1)
    creds = _env_credentials(provider_id)
    if creds is None:
        raise ModelConfigError(f"provider 未启用(缺少密钥): {provider_id}")
    return _build_model(provider_id, model_id, creds)


def default_model_id() -> str:
    """返回默认可用模型(仅看环境变量)。新代码请用 adefault_model_id。"""
    s = get_settings()
    if s.openai_compatible_api_key and s.openai_compatible_api_base_url:
        first = next(
            (m.strip() for m in s.openai_compatible_models.split(",") if m.strip()),
            None,
        )
        if first:
            return f"openai-compatible:{first}"
    if s.deepseek_api_key:
        return "deepseek:deepseek-chat"
    if s.openai_api_key:
        return "openai:gpt-4o-mini"
    if s.anthropic_api_key:
        return "anthropic:claude-haiku-4-5-20251001"
    if s.google_generative_ai_api_key:
        return "google:gemini-2.0-flash"
    raise ModelConfigError("未配置任何 AI 提供商密钥,无法选用默认模型")


# ---------------------------------------------------------------------------
# 异步路径(BYOK 感知)——路由/智能体使用
# ---------------------------------------------------------------------------


async def _user_credentials(provider_id: str, user_id: str) -> ProviderCredentials | None:
    """从 user_api_keys 表取该用户的 provider 凭据。无记录/未启用返回 None。"""
    if not user_id:
        return None

    from sqlalchemy import select

    from ryoshi.crypto import CryptoError, decrypt_api_key
    from ryoshi.db.engine import get_session_factory
    from ryoshi.db.models import UserApiKey

    async with get_session_factory()() as session:
        row = (
            await session.execute(
                select(UserApiKey).where(
                    UserApiKey.user_id == user_id,
                    UserApiKey.provider == provider_id,
                    UserApiKey.enabled.is_(True),
                )
            )
        ).scalar_one_or_none()

        if row is None:
            return None

        # 在 session 内读取所有属性,避免 DetachedInstanceError
        encrypted_api_key = row.encrypted_api_key
        base_url = row.base_url or ""
        models_raw = row.models or ""
        provider_name = row.provider_name or ""

    # session 已关闭,后续操作只用上面读出的原始值
    try:
        api_key = decrypt_api_key(encrypted_api_key)
    except CryptoError:
        # 密钥解不出(加密 key 变更等)按"未配置"处理,回退到环境变量
        return None

    # models 存 JSON 数组字符串,解析为逗号分隔供内部使用
    # 兼容旧格式:如果已经是逗号分隔(无 [ ]),直接使用
    models_parsed = ""
    if models_raw:
        import json

        try:
            models_list = json.loads(models_raw)
            if isinstance(models_list, list):
                models_parsed = ",".join(str(m) for m in models_list)
            else:
                models_parsed = models_raw
        except (ValueError, TypeError):
            # 旧格式:逗号分隔字符串
            models_parsed = models_raw

    return ProviderCredentials(
        api_key=api_key,
        base_url=base_url,
        models=models_parsed,
        provider_name=provider_name,
        source="user",
    )


async def _resolve_credentials(
    provider_id: str, user_id: str | None
) -> ProviderCredentials | None:
    """BYOK 解析:登录用户只用自己的密钥;未登录用环境变量兜底。

    语义(与部署阶段对齐):
      - 未登录(匿名/访客): 用全局环境变量。开发期方便,上线后删掉
        .env 里的 key 即变成"必须登录+配 key 才能用"。
      - 已登录: 只用 user_api_keys 表里自己的密钥;没配就是"未启用",
        绝不回退到环境变量——key 与用户身份严格绑定。
    """
    if user_id:
        return await _user_credentials(provider_id, user_id)
    return _env_credentials(provider_id)


async def _all_user_credentials(user_id: str) -> dict[str, ProviderCredentials]:
    """一次性获取当前用户所有 provider 的凭据(减少 N+1 查询)。

    返回: {provider_id: ProviderCredentials}
    未配置或解密失败的 provider 不在返回字典中。
    """
    if not user_id:
        return {}

    from sqlalchemy import select

    from ryoshi.crypto import CryptoError, decrypt_api_key
    from ryoshi.db.engine import get_session_factory
    from ryoshi.db.models import UserApiKey

    async with get_session_factory()() as session:
        rows = (
            await session.execute(
                select(UserApiKey).where(
                    UserApiKey.user_id == user_id,
                    UserApiKey.enabled.is_(True),
                )
            )
        ).scalars().all()

        # 在 session 内读取所有属性
        row_data = [
            {
                "provider": row.provider,
                "encrypted_api_key": row.encrypted_api_key,
                "base_url": row.base_url or "",
                "models_raw": row.models or "",
                "provider_name": row.provider_name or "",
            }
            for row in rows
        ]

    result: dict[str, ProviderCredentials] = {}
    for data in row_data:
        try:
            api_key = decrypt_api_key(data["encrypted_api_key"])
        except CryptoError:
            continue  # 解密失败,跳过该 provider

        # 解析 models JSON
        models_parsed = ""
        if data["models_raw"]:
            import json

            try:
                models_list = json.loads(data["models_raw"])
                if isinstance(models_list, list):
                    models_parsed = ",".join(str(m) for m in models_list)
                else:
                    models_parsed = data["models_raw"]
            except (ValueError, TypeError):
                models_parsed = data["models_raw"]

        result[data["provider"]] = ProviderCredentials(
            api_key=api_key,
            base_url=data["base_url"],
            models=models_parsed,
            provider_name=data["provider_name"],
            source="user",
        )

    return result


async def ais_provider_enabled(provider_id: str, user_id: str | None = None) -> bool:
    """异步版 is_provider_enabled:用户密钥或环境变量任一可用即为 True。"""
    return (await _resolve_credentials(provider_id, user_id)) is not None


# ---- 模型实例缓存 ----
# 每条消息原本都重建 ChatModel:一次 DB 查询(解密 BYOK key)+ 客户端
# 构造;连续对话下重复且无谓。按 (user_id, provider, model, api_key指纹)
# 缓存构造结果——api_key 进 key 保证换 key 立即失效;再叠 5 分钟 TTL
# 兜底(base_url/models 等次要字段变更的场景,代价是至多 5 分钟延迟)。
# ChatModel 实例线程安全(LangChain 官方语义:配置不可变,调用无状态)。
_MODEL_CACHE: dict[tuple, tuple[BaseChatModel, float]] = {}
_MODEL_CACHE_TTL_SECONDS = 300


def _cache_key(provider_id: str, model_id: str, user_id: str | None, api_key: str) -> tuple:
    """缓存键:api_key 用指纹(前 8 字符 + 长度)——明文做 key 有泄漏面
    (异常堆栈/repr 可能带出),指纹足够区分变更。"""
    import hashlib

    key_fp = hashlib.sha256(api_key.encode()).hexdigest()[:12]
    return (user_id or "-", provider_id, model_id, key_fp)


def _cache_get(key: tuple) -> BaseChatModel | None:
    """取缓存;过期条目顺手清除。"""
    import time

    entry = _MODEL_CACHE.get(key)
    if entry is None:
        return None
    model, expires_at = entry
    if time.monotonic() > expires_at:
        _MODEL_CACHE.pop(key, None)
        return None
    return model


def _cache_put(key: tuple, model: BaseChatModel) -> None:
    """写缓存;超上限(防 BYOK 用户多导致内存膨胀)时按简易 LRU 淘汰。"""
    import time

    if len(_MODEL_CACHE) >= 256:
        # 淘汰最早过期的一批(近似 LRU;够用,不值得引 OrderedDict 复杂度)
        for k in sorted(_MODEL_CACHE, key=lambda k: _MODEL_CACHE[k][1])[:64]:
            _MODEL_CACHE.pop(k, None)
    _MODEL_CACHE[key] = (model, time.monotonic() + _MODEL_CACHE_TTL_SECONDS)


async def aget_model(full_model: str, user_id: str | None = None) -> BaseChatModel:
    """把 "providerId:modelId" 解析成 LangChain 聊天模型(BYOK 感知)。

    结果按 (user, provider, model, key指纹) 缓存 5 分钟:连续对话不再
    重复 DB 查询与客户端构造;换 key 立即失效(指纹变化)。

    参数:
        full_model: 形如 "openai:gpt-4o-mini"、"anthropic:claude-haiku-4-5"
        user_id: 当前登录用户 id(匿名/未登录传 None,只查环境变量)
    返回:
        已配置好密钥、可直接 .bind_tools() / .astream() 的 ChatModel。
    """
    if ":" not in full_model:
        raise ModelConfigError(f"模型标识缺少 provider 前缀: {full_model!r}")
    provider_id, model_id = full_model.split(":", 1)

    creds = await _resolve_credentials(provider_id, user_id)
    if creds is None:
        raise ModelConfigError(f"provider 未启用(缺少密钥): {provider_id}")

    cache_key = _cache_key(provider_id, model_id, user_id, creds.api_key)
    cached = _cache_get(cache_key)
    if cached is not None:
        return cached

    model = _build_model(provider_id, model_id, creds)
    _cache_put(cache_key, model)
    return model


async def adefault_model_id(user_id: str | None = None) -> str:
    """返回默认可用模型(BYOK 感知)。

    策略:
      - 登录用户:返回第一个已配置的模型;一个都没配则报错
      - 匿名用户:从环境变量读 openai-compatible 的默认模型(开发期用)
    """
    if user_id:
        # 登录用户:一次性查所有凭据,找第一个配置了 key 且选了模型的 provider
        all_creds = await _all_user_credentials(user_id)
        for provider_id in BYOK_PROVIDERS:
            creds = all_creds.get(provider_id)
            if creds is not None and creds.models:
                first = next(
                    (m.strip() for m in creds.models.split(",") if m.strip()),
                    None,
                )
                if first:
                    return f"{provider_id}:{first}"
        raise ModelConfigError(
            "未选择模型。请先在 API Keys 设置中配置并选择模型。"
        )

    # 匿名用户:从环境变量读 openai-compatible 默认模型
    s = get_settings()
    if s.openai_compatible_api_key and s.openai_compatible_api_base_url:
        first = next(
            (m.strip() for m in s.openai_compatible_models.split(",") if m.strip()),
            None,
        )
        if first:
            return f"openai-compatible:{first}"

    raise ModelConfigError("未配置任何 AI 提供商密钥,无法选用默认模型")


async def aget_openai_compatible_meta(
    user_id: str | None = None,
) -> ProviderCredentials | None:
    """给 /api/models 用:取 openai-compatible 的完整元信息(含 models 清单)。"""
    return await _resolve_credentials("openai-compatible", user_id)


# ---------------------------------------------------------------------------
# 构造 LangChain 模型(同步,纯工厂)
# ---------------------------------------------------------------------------


class ReasoningCapableChatOpenAI(_OpenAIModelBase):
    """保留 reasoning_content 的 ChatOpenAI 子类。

    背景:langchain-openai(1.6.0)的 _convert_delta_to_message_chunk 只取
    content/function_call/tool_calls,DeepSeek-R1 等推理模型的
    delta.reasoning_content 会被静默丢弃——思考链整条链路(帧模型/前端
    reasoning-section/DB reasoning 列)全部就位,唯独这里断了。

    做法:包一层 _convert_chunk_to_generation_chunk,从原始 chunk dict
    (LangGraph 事件里拿不到,但转换入口拿得到)把 reasoning_content
    补进 message.additional_kwargs;下游 chat/stream.py 据此产出
    reasoning-start/delta/end 帧。
    """

    def _convert_chunk_to_generation_chunk(
        self, chunk, default_chunk_class, base_generation_info
    ):
        generation = super()._convert_chunk_to_generation_chunk(
            chunk, default_chunk_class, base_generation_info
        )
        if generation is None:
            return None
        choices = chunk.get("choices") or chunk.get("chunk", {}).get("choices", [])
        if not choices:
            return generation
        delta = choices[0].get("delta") or {}
        reasoning = delta.get("reasoning_content") or delta.get("reasoning")
        if isinstance(reasoning, str) and reasoning:
            generation.message.additional_kwargs["reasoning_content"] = (
                generation.message.additional_kwargs.get("reasoning_content", "") + reasoning
            )
        return generation


def _build_model(
    provider_id: str, model_id: str, creds: ProviderCredentials
) -> BaseChatModel:
    """按 provider 构造 LangChain ChatModel。"""
    if provider_id == "openai":

        return ReasoningCapableChatOpenAI(model=model_id, api_key=creds.api_key)
    if provider_id == "anthropic":
        from langchain_anthropic import ChatAnthropic

        return ChatAnthropic(model=model_id, api_key=creds.api_key)
    if provider_id == "google":
        from langchain_google_genai import ChatGoogleGenerativeAI

        return ChatGoogleGenerativeAI(model=model_id, google_api_key=creds.api_key)
    if provider_id == "deepseek":
        # DeepSeek 是 OpenAI 兼容 API:用 ChatOpenAI 改 base_url 即可接入
        # (deepseek-reasoner 的 reasoning_content 经 ReasoningCapable 子类保留)
        return ReasoningCapableChatOpenAI(
            model=model_id,
            api_key=creds.api_key,
            base_url=creds.base_url or "https://api.deepseek.com",
        )
    if provider_id == "openai-compatible":
        # 通用兼容端点(可能托管 Qwen-R1 等推理模型),同样保留 reasoning
        return ReasoningCapableChatOpenAI(
            model=model_id,
            api_key=creds.api_key,
            base_url=creds.base_url,
        )

    raise ModelConfigError(f"暂不支持的 provider: {provider_id}")
