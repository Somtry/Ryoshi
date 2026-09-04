"""模型选择器数据接口:GET /api/models。

设计意图:
    对应原项目 lib/model-selector/get-model-selector-data.ts(服务端组装)。
    前端 chat-panel 的 ModelSelectorClient 需要这份数据来渲染模型下拉框:
    哪些 provider 可用、每个 provider 下有哪些模型、当前选中的模型 key。

    BYOK 改造:
      携带合法 JWT 的登录用户,可用模型由"该用户的 user_api_keys 表"
      决定(用户密钥优先);匿名用户或未登录时回退到全局环境变量。
      openai-compatible 的模型清单来源也因此分两支:
        - 用户配了 → 用用户填的 models 字符串
        - 否则     → 用 OPENAI_COMPATIBLE_MODELS 环境变量
"""

from fastapi import APIRouter, Header

from ryoshi.agents.models import ProviderCredentials
from ryoshi.agents.models import (
    ModelConfigError,
    _all_user_credentials,
    _resolve_credentials,
    adefault_model_id,
    aget_openai_compatible_meta,
    ais_provider_enabled,
    is_provider_enabled,
)
from ryoshi.auth import resolve_user
from ryoshi.config import get_settings

router = APIRouter(prefix="/api", tags=["models"])

# 各 provider 的已知模型静态清单(与原项目 fetch-models 的返回对齐)。
# 只列 Ryoshi 实际支持的;openai-compatible 走用户/环境变量动态配置。
_STATIC_MODELS: dict[str, list[dict]] = {
    "openai": [
        {"id": "gpt-4o-mini", "name": "GPT-4o Mini", "provider": "OpenAI", "providerId": "openai"},
    ],
    "anthropic": [
        {"id": "claude-haiku-4-5-20251001", "name": "Claude Haiku 4.5", "provider": "Anthropic", "providerId": "anthropic"},
    ],
    "google": [
        {"id": "gemini-2.0-flash", "name": "Gemini 2.0 Flash", "provider": "Google", "providerId": "google"},
    ],
    "deepseek": [
        {"id": "deepseek-chat", "name": "DeepSeek Chat", "provider": "DeepSeek", "providerId": "deepseek"},
    ],
}


@router.get("/models")
async def get_models(authorization: str | None = Header(None)):
    """返回模型选择器数据。匿名模式下也可用(模型选择不需要登录)。"""
    s = get_settings()
    # 登录用户走 BYOK;匿名/未登录只看环境变量
    user = await resolve_user(authorization, allow_anonymous_fallback=True)
    user_id = None if user.is_anonymous else user.id

    models_by_provider: dict[str, list[dict]] = {}

    # 登录用户:一次性查所有凭据(N+1 修复)
    all_creds: dict[str, ProviderCredentials] = {}
    if user_id:
        all_creds = await _all_user_credentials(user_id)

    # openai-compatible:凭据(含 models 清单与显示名)来自用户或环境变量
    oc = all_creds.get("openai-compatible") if user_id else await aget_openai_compatible_meta(None)
    if oc is not None and oc.models:
        label = oc.provider_name or "OpenAI Compatible"
        models = [
            {"id": m.strip(), "name": m.strip(), "provider": label, "providerId": "openai-compatible"}
            for m in oc.models.split(",")
            if m.strip()
        ]
        if models:
            models_by_provider["openai-compatible"] = models

    # 静态 provider:用户配了且选了模型才列出(不再硬编码静态列表)
    # 静态 provider 也支持动态发现模型
    for provider_id in ("openai", "anthropic", "google", "deepseek"):
        creds = all_creds.get(provider_id) if user_id else await _resolve_credentials(provider_id, None)
        if creds is not None and creds.models:
            # 用户配置了该 provider 并勾选了模型
            models = [
                {
                    "id": m.strip(),
                    "name": m.strip(),
                    "provider": provider_id.capitalize(),
                    "providerId": provider_id,
                }
                for m in creds.models.split(",")
                if m.strip()
            ]
            if models:
                models_by_provider[provider_id] = models
        elif not user_id and is_provider_enabled(provider_id):
            # 未登录用户(开发期):用静态默认列表
            if provider_id in _STATIC_MODELS:
                models_by_provider[provider_id] = _STATIC_MODELS[provider_id]

    # 当前选中:与后端实际默认模型保持一致(adefault_model_id 的优先级),
    # 避免"选择器显示 anthropic 而后端跑 openai-compatible"的不一致。
    try:
        selected_key = await adefault_model_id(user_id)
    except ModelConfigError:
        selected_key = ""

    return {
        "enabled": True,
        "modelsByProvider": models_by_provider,
        "selectedModelKey": selected_key,
        "hasAvailableModels": bool(models_by_provider),
        # 认证模式:前端据此区分"匿名模式"(ENABLE_AUTH=false,单用户共享
        # anonymous-user,应视为已登录)与"未登录的访客"(需登录才能上传等)。
        # 原型靠服务端 getCurrentUserId() 直接返回 anonymous-user 解决;
        # SPA 前端只能问后端。
        "authMode": "authenticated" if s.enable_auth else "anonymous",
        "anonymousUserId": s.anonymous_user_id if not s.enable_auth else None,
    }
