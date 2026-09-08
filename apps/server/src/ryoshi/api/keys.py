"""BYOK 用户密钥管理接口:/api/keys。

设计意图:
    对应"设置页 → API 密钥"的增删改查。只服务于登录用户
    (ENABLE_AUTH=true 且带合法 JWT);匿名模式直接 404(没意义)。

    安全约束:
      - 密钥用 Fernet 加密后落库(见 ryoshi.crypto),任何接口都不回显明文
      - 每个用户每个 provider 至多一条(upsert 语义)
      - 只有 openai-compatible 接受 base_url / models / provider_name

    模型发现:
      POST /api/keys/discover-models 接收 base_url + api_key,
      代理请求 {base_url}/models 拉取可用模型列表,返回供用户勾选。
      支持 OpenAI 兼容端点(DeepSeek、Moonshot、自建 vLLM 等)。
"""

import json

import httpx
from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ryoshi.auth import AuthError, AuthUser, resolve_user
from ryoshi.config import get_settings
from ryoshi.crypto import CryptoError, encrypt_api_key, mask_api_key
from ryoshi.db.engine import get_session
from ryoshi.db.models import UserApiKey
from ryoshi.netguard import NetGuardError, avalidate_outbound_url

router = APIRouter(prefix="/api/keys", tags=["keys"])

#: 支持 BYOK 的 provider 列表(与 agents/models.py 保持一致)
_BYOK_PROVIDERS = ("openai", "anthropic", "google", "deepseek", "openai-compatible")


async def _current_user_required(authorization: str | None = Header(None)) -> AuthUser:
    """强制要求登录。匿名模式或未登录返回 401。"""
    s = get_settings()
    if not s.enable_auth:
        # 匿名模式下 BYOK 无意义(所有用户共享一个 anonymous-user)
        raise HTTPException(status_code=404, detail="Not found")
    try:
        user = await resolve_user(authorization, allow_anonymous_fallback=False)
    except AuthError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc
    return user


def _validate_models_json(models_str: str) -> list[str]:
    """校验 models 是合法 JSON 字符串数组,返回解析后的列表。

    用于 BYOK 配置时校验用户勾选的模型列表格式。
    """
    if not models_str or not models_str.strip():
        raise HTTPException(status_code=400, detail="models 不能为空")

    try:
        models_list = json.loads(models_str)
        if not isinstance(models_list, list) or not all(
            isinstance(m, str) for m in models_list
        ):
            raise ValueError
        if not models_list:
            raise HTTPException(status_code=400, detail="至少选择一个模型")
        return models_list
    except (ValueError, TypeError) as exc:
        raise HTTPException(
            status_code=400,
            detail='models 必须是 JSON 数组,如 ["model-a","model-b"]',
        ) from exc


class KeyUpsertRequest(BaseModel):
    """新增/覆盖某 provider 的密钥。"""

    api_key: str | None = None  # None 表示保留已有密钥(仅当已存在时有效)
    # 以下字段 openai-compatible 必须,其他 provider 也支持(用于动态模型)
    base_url: str | None = None
    models: str | None = None  # JSON 字符串数组,如 '["deepseek-chat","deepseek-reasoner"]'
    provider_name: str | None = None


class DiscoverModelsRequest(BaseModel):
    """模型发现请求。"""

    api_key: str | None = None  # None 表示用已有密钥(仅当该 provider 已配置时有效)
    base_url: str = Field(min_length=1)
    provider: str = "openai-compatible"  # 用于确定调哪个 API 路径


class DiscoveredModel(BaseModel):
    """从 OpenAI 兼容端点发现的单个模型。"""

    id: str
    name: str
    description: str | None = None


class KeySummary(BaseModel):
    """列表/详情响应里的密钥摘要(不含明文)。"""

    provider: str
    masked_key: str
    base_url: str | None = None
    models: list[str] | None = None  # JSON 数组,用户勾选的模型列表
    provider_name: str | None = None
    enabled: bool


def _to_summary(row: UserApiKey) -> KeySummary:
    """把 ORM 行转成响应摘要。解密失败时用占位符,不阻断列表。"""
    from ryoshi.crypto import decrypt_api_key

    try:
        masked = mask_api_key(decrypt_api_key(row.encrypted_api_key))
    except CryptoError:
        masked = "••••(密钥不可用,请重新配置)"

    # models 存 JSON 数组,返回时解析为 list 供前端渲染
    models_list: list[str] = []
    if row.models:
        import json

        try:
            models_list = json.loads(row.models)
        except (ValueError, TypeError):
            # 兼容旧格式:逗号分隔字符串
            models_list = [m.strip() for m in row.models.split(",") if m.strip()]

    return KeySummary(
        provider=row.provider,
        masked_key=masked,
        base_url=row.base_url,
        models=models_list,
        provider_name=row.provider_name,
        enabled=row.enabled,
    )


@router.get("")
async def list_keys(
    session: AsyncSession = Depends(get_session),
    user: AuthUser = Depends(_current_user_required),
) -> dict:
    """列出当前用户已配置的全部 provider 密钥(掩码形式)。"""
    rows = (
        await session.execute(
            select(UserApiKey).where(UserApiKey.user_id == user.id)
        )
    ).scalars().all()
    return {
        "keys": [_to_summary(r).model_dump() for r in rows],
        "providers": list(_BYOK_PROVIDERS),
    }


@router.put("/{provider}")
async def upsert_key(
    provider: str,
    payload: KeyUpsertRequest,
    session: AsyncSession = Depends(get_session),
    user: AuthUser = Depends(_current_user_required),
) -> dict:
    """新增或覆盖某 provider 的密钥。

    openai-compatible 必须带 base_url 与 models(逗号分隔);
    其他 provider 会忽略 base_url/models/provider_name。
    """
    if provider not in _BYOK_PROVIDERS:
        raise HTTPException(status_code=400, detail=f"不支持的 provider: {provider}")

    if provider == "openai-compatible":
        if not payload.base_url or not payload.base_url.strip():
            raise HTTPException(status_code=400, detail="openai-compatible 需要 base_url")
        if not payload.models or not payload.models.strip():
            raise HTTPException(
                status_code=400, detail="openai-compatible 需要 models(JSON 数组)"
            )

    # 校验 models 格式(所有 provider 通用)
    if payload.models:
        _validate_models_json(payload.models)

    # 找已有记录
    existing = (
        await session.execute(
            select(UserApiKey).where(
                UserApiKey.user_id == user.id, UserApiKey.provider == provider
            )
        )
    ).scalar_one_or_none()

    # 处理 API key:None 表示保留已有密钥(仅当已存在时有效)
    if payload.api_key is None:
        if existing is None:
            raise HTTPException(status_code=400, detail="未提供 API key")
        encrypted = existing.encrypted_api_key
    else:
        try:
            encrypted = encrypt_api_key(payload.api_key)
        except CryptoError as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc

    if existing is None:
        existing = UserApiKey(user_id=user.id, provider=provider)
        session.add(existing)

    existing.encrypted_api_key = encrypted
    # 所有 provider 都存 models(支持动态选择)
    existing.models = payload.models.strip() if payload.models else None

    if provider == "openai-compatible":
        existing.base_url = payload.base_url.strip() if payload.base_url else None
        existing.provider_name = (
            payload.provider_name.strip() if payload.provider_name else None
        )
    else:
        existing.base_url = None
        existing.provider_name = None
    existing.enabled = True

    await session.commit()
    return _to_summary(existing).model_dump()


async def _validate_base_url(base_url: str) -> None:
    """SSRF 防护:校验 base_url 指向合法的公网 HTTP(S) 端点。

    私网/黑名单/DNS 解析检查统一委托 ryoshi.netguard(与 fetch 工具
    共用同一份清单);这里只补充 BYOK 特有的协议规则:
    生产环境强制 https(开发环境允许 http)。
    """
    if not base_url:
        raise HTTPException(status_code=400, detail="base_url 不能为空")

    s = get_settings()
    is_dev = s.environment == "development"
    if base_url.startswith("http://") and not is_dev:
        raise HTTPException(status_code=400, detail="生产环境必须使用 https://")

    try:
        await avalidate_outbound_url(base_url)
    except NetGuardError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/discover-models")
async def discover_models(
    payload: DiscoverModelsRequest,
    session: AsyncSession = Depends(get_session),
    user: AuthUser = Depends(_current_user_required),
) -> dict:
    """从各 provider 拉取可用模型列表。

    支持:
      - openai / openai-compatible: GET {base_url}/models
      - anthropic: GET https://api.anthropic.com/v1/models
      - google: GET https://generativelanguage.googleapis.com/v1beta/models
      - deepseek: GET https://api.deepseek.com/models

    SSRF 防护:校验 base_url 指向合法公网端点,禁止私有 IP/保留地址。

    api_key 为 None 时,尝试用该 provider 已保存的密钥(编辑现有配置时)。
    """
    provider = payload.provider
    api_key = payload.api_key
    base_url = payload.base_url.rstrip("/")

    # api_key 为 None:尝试用该 provider 已保存的密钥
    if api_key is None:
        from ryoshi.db.models import UserApiKey

        existing = (
            await session.execute(
                select(UserApiKey).where(
                    UserApiKey.user_id == user.id, UserApiKey.provider == provider
                )
            )
        ).scalar_one_or_none()
        if existing is None:
            raise HTTPException(status_code=400, detail="该 provider 未配置密钥")
        from ryoshi.crypto import decrypt_api_key

        try:
            api_key = decrypt_api_key(existing.encrypted_api_key)
        except CryptoError as exc:
            raise HTTPException(status_code=400, detail="已保存的密钥无法解密,请重新输入") from exc

    # SSRF 防护:校验 base_url
    if provider == "openai-compatible":
        await _validate_base_url(base_url)

    # 对已知 provider,使用官方端点(不校验,因为 host 是固定的)
    effective_base_url = base_url
    if provider == "openai":
        effective_base_url = "https://api.openai.com/v1"
    elif provider == "anthropic":
        effective_base_url = "https://api.anthropic.com"
    elif provider == "google":
        effective_base_url = "https://generativelanguage.googleapis.com"
    elif provider == "deepseek":
        effective_base_url = "https://api.deepseek.com"

    async with httpx.AsyncClient(timeout=30.0, follow_redirects=False) as client:
        try:
            if provider in ("openai", "openai-compatible"):
                resp = await client.get(
                    f"{effective_base_url}/models",
                    headers={"Authorization": f"Bearer {api_key}"},
                )
            elif provider == "anthropic":
                resp = await client.get(
                    f"{effective_base_url}/v1/models",
                    headers={
                        "x-api-key": api_key,
                        "anthropic-version": "2023-06-01",
                    },
                )
            elif provider == "google":
                # 修复:改用 header 而非 URL query 传递 API key,避免泄露到日志
                resp = await client.get(
                    f"{effective_base_url}/v1beta/models",
                    headers={"x-goog-api-key": api_key},
                )
            elif provider == "deepseek":
                resp = await client.get(
                    f"{effective_base_url}/models",
                    headers={"Authorization": f"Bearer {api_key}"},
                )
            else:
                raise HTTPException(status_code=400, detail=f"不支持的 provider: {provider}")

            resp.raise_for_status()
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code == 401:
                raise HTTPException(status_code=400, detail="API key 无效或已过期") from exc
            raise HTTPException(
                status_code=400,
                detail=f"无法获取模型列表: HTTP {exc.response.status_code}",
            ) from exc
        except httpx.RequestError as exc:
            # 修复:不泄露底层异常细节(可能包含内部网络信息)
            error_type = type(exc).__name__
            raise HTTPException(
                status_code=400, detail=f"无法连接到服务端: {error_type}"
            ) from exc

    try:
        data = resp.json()
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="端点返回的不是合法 JSON") from exc

    # 不同 provider 返回格式不同
    raw_models = []
    if provider == "google":
        # Google: {"models": [{"name": "models/gemini-2.0-flash", ...}]}
        raw_models = data.get("models", [])
    else:
        # OpenAI 兼容: {"data": [...]} 或直接 [...]
        raw_models = data.get("data", data) if isinstance(data, dict) else data

    if not isinstance(raw_models, list):
        raise HTTPException(
            status_code=400,
            detail=f"无法解析模型列表,期望数组,得到: {type(raw_models).__name__}",
        )

    models = []
    for m in raw_models:
        if provider == "google":
            # Google 格式: {"name": "models/gemini-2.0-flash", "displayName": "Gemini 2.0 Flash"}
            model_id = m.get("name", "").replace("models/", "")
            if model_id:
                models.append(
                    DiscoveredModel(
                        id=model_id,
                        name=m.get("displayName", model_id),
                        description=m.get("description"),
                    )
                )
        elif isinstance(m, dict) and m.get("id"):
            models.append(
                DiscoveredModel(
                    id=m["id"],
                    name=m.get("id", ""),
                    description=m.get("description") or m.get("owned_by"),
                )
            )
        elif isinstance(m, str):
            models.append(DiscoveredModel(id=m, name=m))

    return {"models": [m.model_dump() for m in models]}


@router.delete("/{provider}", status_code=204)
async def delete_key(
    provider: str,
    session: AsyncSession = Depends(get_session),
    user: AuthUser = Depends(_current_user_required),
) -> None:
    """删除某 provider 的密钥。不存在返回 404。"""
    existing = (
        await session.execute(
            select(UserApiKey).where(
                UserApiKey.user_id == user.id, UserApiKey.provider == provider
            )
        )
    ).scalar_one_or_none()
    if existing is None:
        raise HTTPException(status_code=404, detail="Key not found")
    await session.delete(existing)
    await session.commit()
