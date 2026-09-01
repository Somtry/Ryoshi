"""模型选择器数据接口:GET /api/models。

设计意图:
    对应原项目 lib/model-selector/get-model-selector-data.ts(服务端组装)。
    前端 chat-panel 的 ModelSelectorClient 需要这份数据来渲染模型下拉框:
    哪些 provider 可用、每个 provider 下有哪些模型、当前选中的模型 key。

    模型清单来源:
      - openai-compatible: 直接用 OPENAI_COMPATIBLE_MODELS 环境变量(逗号分隔)
      - 其他 provider: 有 API key 就列出该 provider 的已知模型(静态清单)
"""

from fastapi import APIRouter

from ryoshi.agents.models import ModelConfigError, default_model_id, is_provider_enabled
from ryoshi.config import get_settings

router = APIRouter(prefix="/api", tags=["models"])

# 各 provider 的已知模型静态清单(与原项目 fetch-models 的返回对齐)。
# 只列 Ryoshi 实际支持的;openai-compatible 走环境变量动态配置。
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
async def get_models():
    """返回模型选择器数据。匿名模式下也可用(模型选择不需要登录)。"""
    s = get_settings()
    models_by_provider: dict[str, list[dict]] = {}

    # openai-compatible:从环境变量 OPENAI_COMPATIBLE_MODELS 读
    if is_provider_enabled("openai-compatible"):
        models = [
            {"id": m.strip(), "name": m.strip(), "provider": "OpenAI Compatible", "providerId": "openai-compatible"}
            for m in s.openai_compatible_models.split(",")
            if m.strip()
        ]
        if models:
            models_by_provider["openai-compatible"] = models

    # 静态 provider:有 key 就列出
    for provider_id, models in _STATIC_MODELS.items():
        if is_provider_enabled(provider_id):
            models_by_provider[provider_id] = models

    # 当前选中:与后端实际默认模型保持一致(default_model_id 的优先级),
    # 避免"选择器显示 anthropic 而后端跑 openai-compatible"的不一致。
    try:
        selected_key = default_model_id()
    except ModelConfigError:
        selected_key = ""

    return {
        "enabled": True,
        "modelsByProvider": models_by_provider,
        "selectedModelKey": selected_key,
        "hasAvailableModels": bool(models_by_provider),
    }
