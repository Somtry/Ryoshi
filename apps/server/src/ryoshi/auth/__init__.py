"""Supabase JWT 校验(对应原项目 lib/auth/get-current-user.ts)。

设计意图:
    原项目在 Next.js 服务端用 @supabase/ssr 的 createServerClient + getUser()
    校验——本质是向 Supabase API 发一次请求验证 token 有效性。
    Ryoshi 后端是常驻 Python 服务,每次请求都调一次 Supabase API 会成为瓶颈;
    改为本地校验 JWT 签名,验证通过后直接从 payload 取 sub(用户 id),零网络开销。

    签名密钥两种形态(取决于 Supabase 项目的 JWT Keys 配置):
      1. 新版 ECC(P-256,算法 ES256)非对称签名——从 JWKS 端点拉公钥校验,
         私钥不离开 Supabase,且能自动跟上 key 轮换。这是 Supabase 现行默认。
      2. 旧版 HS256 共享密钥(JWT Secret)——本地用同一 secret 校验。

    校验策略:优先 JWKS(配置了 SUPABASE_URL 即可,无需额外密钥);
    未配置 URL 但配了 SUPABASE_JWT_SECRET 时回退 HS256(兼容老项目/自建)。

    匿名模式(ENABLE_AUTH=false)完全保留:所有请求共享 ANONYMOUS_USER_ID,
    与原项目 getCurrentUserId 的行为对齐。
"""

import asyncio
import logging
import time
from dataclasses import dataclass

import httpx
from jose import JWTError, jwt
from jose.exceptions import JWKError

from ryoshi.config import get_settings

logger = logging.getLogger("ryoshi.auth")

# JWKS 公钥缓存:{"keys": [...], "fetched_at": 时间戳}
# 模块级缓存,进程内共享;避免每个请求都打一次 Supabase。
_jwks_cache: dict = {}
# 缓存有效期。Supabase 的 key 轮换会先发 standby 再切换,公钥端点会同时
# 返回新旧 key,所以缓存几小时是安全的;遇到未知 kid 也会主动刷新(见下)。
_JWKS_TTL_SECONDS = 3600

# 异步锁:防止并发请求同时拉取 JWKS(thundering herd)
_jwks_lock: asyncio.Lock | None = None


@dataclass(frozen=True)
class AuthUser:
    """已通过身份验证的用户。匿名模式下 id 即 ANONYMOUS_USER_ID。"""

    id: str
    is_anonymous: bool


class AuthError(Exception):
    """认证失败(token 缺失/无效/过期)。路由层捕获后返回 401。"""


def _extract_bearer_token(authorization: str | None) -> str:
    """从 Authorization header 提取 Bearer token。缺失或格式错误抛 AuthError。"""
    if not authorization:
        raise AuthError("缺少 Authorization header")
    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or not token:
        raise AuthError("Authorization header 格式应为 'Bearer <token>'")
    return token


def _jwks_url(supabase_url: str) -> str:
    """Supabase 的 JWKS 公钥端点(对应 JS 客户端校验 token 用的同一套公钥)。"""
    return f"{supabase_url.rstrip('/')}/auth/v1/.well-known/jwks.json"


async def _fetch_jwks(supabase_url: str, *, force_refresh: bool = False) -> list[dict]:
    """拉取 JWKS 公钥列表,带 TTL 缓存。失败抛 AuthError。

    修复:
      - 改为异步,避免阻塞 event loop
      - 加 asyncio.Lock 防止并发重复拉取
      - 错误消息不泄露内部细节
    """
    global _jwks_lock
    if _jwks_lock is None:
        _jwks_lock = asyncio.Lock()

    now = time.time()
    if (
        not force_refresh
        and _jwks_cache.get("keys") is not None
        and now - _jwks_cache.get("fetched_at", 0) < _JWKS_TTL_SECONDS
    ):
        return _jwks_cache["keys"]

    async with _jwks_lock:
        # 再次检查缓存(可能在等待锁的过程中被其他请求填充)
        now = time.time()
        if (
            not force_refresh
            and _jwks_cache.get("keys") is not None
            and now - _jwks_cache.get("fetched_at", 0) < _JWKS_TTL_SECONDS
        ):
            return _jwks_cache["keys"]

        url = _jwks_url(supabase_url)
        try:
            from ryoshi.http import get_http_client

            resp = await get_http_client().get(url)
            resp.raise_for_status()
            keys = resp.json().get("keys", [])
        except httpx.HTTPError as exc:
            logger.error(f"JWKS fetch failed: {exc}")
            raise AuthError("认证服务暂时不可用,请稍后重试") from exc
        except (ValueError, KeyError) as exc:
            logger.error(f"JWKS parse failed: {exc}")
            raise AuthError("认证服务响应异常") from exc

        if not keys:
            logger.error("JWKS endpoint returned no keys")
            raise AuthError("认证服务配置异常")

        _jwks_cache["keys"] = keys
        _jwks_cache["fetched_at"] = now
        return keys


def _find_key_for_token(token: str, keys: list[dict]) -> dict | None:
    """按 token header 里的 kid 在 JWKS 列表中找匹配的公钥。"""
    try:
        header = jwt.get_unverified_header(token)
    except JWTError:
        return None
    kid = header.get("kid")
    if not kid:
        # 无 kid 时,若只有一个 key 就用它(常见于单 key 项目)
        return keys[0] if len(keys) == 1 else None
    for k in keys:
        if k.get("kid") == kid:
            return k
    return None


async def verify_jwt(token: str) -> AuthUser:
    """本地校验 Supabase JWT,返回认证用户。

    Supabase JWT 约定:
      - 算法 ES256(新版 ECC 项目)或 HS256(旧版共享密钥项目)
      - payload.sub = 用户 UUID
      - payload.aud = "authenticated"(登录用户)或 "anon"(匿名 key 签发)
      - payload.exp = 过期时间戳
    """
    s = get_settings()

    # 路径 1:JWKS 公钥校验(新版 ECC 项目,配 SUPABASE_URL 即可)
    if s.supabase_url:
        return await _verify_via_jwks(token, s.supabase_url)

    # 路径 2:HS256 共享密钥回退(旧版项目/自建 Supabase)
    if s.supabase_jwt_secret:
        return _verify_via_secret(token, s.supabase_jwt_secret)

    raise AuthError("后端未配置 SUPABASE_URL(用于 JWKS)或 SUPABASE_JWT_SECRET")


async def _verify_via_jwks(token: str, supabase_url: str) -> AuthUser:
    """用 JWKS 公钥校验(ES256/ECC)。未知 kid 会强制刷新一次公钥再试。"""
    keys = await _fetch_jwks(supabase_url)
    key = _find_key_for_token(token, keys)

    if key is None:
        # kid 不在缓存里:可能是 Supabase 轮换了 key,强制刷新再试一次
        keys = await _fetch_jwks(supabase_url, force_refresh=True)
        key = _find_key_for_token(token, keys)
        if key is None:
            raise AuthError("JWT 签名验证失败")

    try:
        payload = jwt.decode(
            token,
            key,
            # 严格限定 ES256:Supabase ECC 项目只用 ES256,不接收 RS256
            algorithms=["ES256"],
            options={"verify_aud": False},
        )
    except (JWTError, JWKError) as exc:
        logger.warning(f"JWT decode failed: {exc}")
        raise AuthError("JWT 无效或已过期") from exc

    return _user_from_payload(payload)


def _verify_via_secret(token: str, secret: str) -> AuthUser:
    """用 HS256 共享密钥校验(旧版项目)。"""
    try:
        payload = jwt.decode(
            token,
            secret,
            algorithms=["HS256"],
            # Supabase 的 aud 是 "authenticated" 或 "anon";不强制校验 aud,
            # 因为 anon key 签发的 token 也是合法的(未登录但有匿名会话的场景)
            options={"verify_aud": False},
        )
    except JWTError as exc:
        raise AuthError(f"JWT 校验失败: {exc}") from exc

    return _user_from_payload(payload)


def _user_from_payload(payload: dict) -> AuthUser:
    """从 JWT payload 提取用户 id。"""
    user_id = payload.get("sub")
    if not user_id or not isinstance(user_id, str):
        raise AuthError("JWT payload 缺少 sub 字段")
    return AuthUser(id=user_id, is_anonymous=False)


async def resolve_user(
    authorization: str | None,
    *,
    allow_anonymous_fallback: bool = True,
) -> AuthUser:
    """统一的认证入口(对应原项目 getCurrentUserId)。

    逻辑(与原项目 getCurrentUserId 对齐):
      1. ENABLE_AUTH=false → 匿名模式,返回共享的 ANONYMOUS_USER_ID
      2. ENABLE_AUTH=true + 有 Bearer token → 校验 JWT,返回真实用户
      3. ENABLE_AUTH=true + 无 token + allow_anonymous_fallback → 匿名用户
         (对应原项目"未登录仍可访问公开路径"的行为)
      4. ENABLE_AUTH=true + 无 token + 不允许匿名 → 抛 AuthError(401)

    原项目的匿名回退:
      getCurrentUserId 在未登录时返回 undefined,调用方(loadChat 等)会按
      "匿名访客"处理——允许浏览公开分享,但不允许写操作。Ryoshi 这里用
      allow_anonymous_fallback 参数让各路由自行决定是否允许匿名。
    """
    s = get_settings()

    # 匿名模式:所有请求共享一个用户 id(与原项目 ENABLE_AUTH=false 一致)
    if not s.enable_auth:
        return AuthUser(id=s.anonymous_user_id, is_anonymous=True)

    # 云端部署强制认证(与原项目 MORPHIC_CLOUD_DEPLOYMENT 的 guard 对齐)
    if s.ryoshi_cloud_deployment and not s.enable_auth:
        raise AuthError("云端部署不允许关闭认证")

    if authorization:
        token = _extract_bearer_token(authorization)
        try:
            return await verify_jwt(token)
        except AuthError:
            # token 无效/过期:允许匿名回退的接口(如 /api/models)按匿名处理,
            # 而不是直接 401——前端可能带着过期的 localStorage token 访问公开接口。
            if allow_anonymous_fallback:
                return AuthUser(id=s.anonymous_user_id, is_anonymous=True)
            raise

    if allow_anonymous_fallback:
        # 未登录但有匿名回退:与原项目"公开路径可匿名访问"对齐
        return AuthUser(id=s.anonymous_user_id, is_anonymous=True)

    raise AuthError("需要登录")
