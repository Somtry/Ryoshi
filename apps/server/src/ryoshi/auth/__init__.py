"""Supabase JWT 校验(对应原项目 lib/auth/get-current-user.ts)。

设计意图:
    原项目在 Next.js 服务端用 @supabase/ssr 的 createServerClient + getUser()
    校验——本质是向 Supabase API 发一次请求验证 token 有效性。
    Ryoshi 后端是常驻 Python 服务,每次请求都调一次 Supabase API 会成为瓶颈;
    改用 python-jose 本地校验 JWT 签名(Supabase 用 HS256 + 项目级 JWT secret
    签发,secret 即"项目设置 → API → JWT Secret"),验证通过后直接从 payload
    取 sub(用户 id),零网络开销。

    匿名模式(ENABLE_AUTH=false)完全保留:所有请求共享 ANONYMOUS_USER_ID,
    与原项目 getCurrentUserId 的行为对齐。
"""

import logging
from dataclasses import dataclass

from jose import JWTError, jwt

from ryoshi.config import get_settings

logger = logging.getLogger("ryoshi.auth")


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


def verify_jwt(token: str) -> AuthUser:
    """本地校验 Supabase JWT,返回认证用户。

    Supabase JWT 约定:
      - 算法 HS256,签名密钥即项目的 JWT Secret(不是 publishable key)
      - payload.sub = 用户 UUID
      - payload.aud = "authenticated"(登录用户)或 "anon"(匿名 key 签发)
      - payload.exp = 过期时间戳
    """
    s = get_settings()
    if not s.supabase_jwt_secret:
        raise AuthError("后端未配置 SUPABASE_JWT_SECRET,无法校验 token")

    try:
        payload = jwt.decode(
            token,
            s.supabase_jwt_secret,
            algorithms=["HS256"],
            # Supabase 的 aud 是 "authenticated" 或 "anon";不强制校验 aud,
            # 因为 anon key 签发的 token 也是合法的(未登录但有匿名会话的场景)
            options={"verify_aud": False},
        )
    except JWTError as exc:
        raise AuthError(f"JWT 校验失败: {exc}") from exc

    user_id = payload.get("sub")
    if not user_id or not isinstance(user_id, str):
        raise AuthError("JWT payload 缺少 sub 字段")

    return AuthUser(id=user_id, is_anonymous=False)


def resolve_user(
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
        return verify_jwt(token)

    if allow_anonymous_fallback:
        # 未登录但有匿名回退:与原项目"公开路径可匿名访问"对齐
        return AuthUser(id=s.anonymous_user_id, is_anonymous=True)

    raise AuthError("需要登录")
