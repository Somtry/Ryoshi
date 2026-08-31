"""Ryoshi 后端配置中心。

设计意图:
    原 morhpic 项目把配置散落在大量 process.env 读取里,难以追踪。
    这里用 pydantic-settings 把所有环境变量集中声明为一组带类型的字段,
    启动时一次性校验——缺什么、类型错什么,启动即报错,而不是运行时才暴露。

    环境变量统一使用 RYOSHI_ 前缀(对应原项目的 MORPHIC_ 前缀)。
    同时也保留不带前缀的常见变量名(如 DATABASE_URL)以兼容本地习惯。
"""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """应用配置。字段默认值面向"本地匿名开发"这一最常见场景。"""

    model_config = SettingsConfigDict(
        # 同时读取 .env 与环境变量;大小写不敏感
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # ---- 服务基础 ----
    #: 是否视为云端部署(对应原 MORPHIC_CLOUD_DEPLOYMENT)。云端会强制认证、收紧匿名能力。
    ryoshi_cloud_deployment: bool = False
    #: 运行环境,影响日志与错误详情是否外露
    environment: str = "development"

    # ---- 数据库 ----
    #: PostgreSQL 连接串(asyncpg 驱动)
    database_url: str = "postgresql+asyncpg://ryoshi:ryoshi@localhost:5432/ryoshi"

    # ---- Redis(搜索缓存 + 限流计数)----
    redis_url: str = "redis://localhost:6379/0"

    # ---- 认证 ----
    #: 是否启用认证。本地单人使用可关掉,所有请求共享一个匿名用户
    enable_auth: bool = False
    #: 匿名模式下的默认用户 id(ENABLE_AUTH=false 时所有请求共用)
    anonymous_user_id: str = "anonymous-user"
    #: Supabase 项目地址与密钥(JWT 校验用)
    supabase_url: str = ""
    supabase_jwt_secret: str = ""

    # ---- AI 提供商密钥(按配置的模型选用其一即可起步)----
    openai_api_key: str = ""
    anthropic_api_key: str = ""
    google_generative_ai_api_key: str = ""
    #: DeepSeek(走专用 provider 的便捷写法,只需 key)
    deepseek_api_key: str = ""
    deepseek_base_url: str = "https://api.deepseek.com"
    #: 通用 OpenAI 兼容端点(DeepSeek 官方推荐写法;也可指向任何兼容服务)
    #: openai_compatible_models 为逗号分隔的模型清单,第一个即默认模型
    openai_compatible_api_key: str = ""
    openai_compatible_api_base_url: str = ""
    openai_compatible_models: str = ""

    # ---- 搜索提供商密钥 ----
    tavily_api_key: str = ""
    brave_api_key: str = ""
    exa_api_key: str = ""
    #: 自托管 SearXNG 的地址(Docker 部署时自动带上)
    searxng_base_url: str = ""
    #: 默认搜索源(tavily / searxng / brave / exa)。失败时按降级链依次尝试。
    search_api: str = "tavily"

    # ---- 文件上传(S3 兼容对象存储:Cloudflare R2 / AWS S3 / MinIO)----
    # 全部为空时上传功能关闭,前端隐藏入口
    r2_account_id: str = ""
    r2_access_key_id: str = ""
    r2_secret_access_key: str = ""
    r2_bucket_name: str = "user-uploads"
    r2_public_url: str = ""
    #: 自定义 S3 端点(MinIO/自建),优先于 R2_ACCOUNT_ID
    s3_endpoint: str = ""

    # ---- 可观测性(可选,留空即关闭)----
    langfuse_public_key: str = ""
    langfuse_secret_key: str = ""
    langfuse_host: str = "https://cloud.langfuse.com"
    posthog_api_key: str = ""
    posthog_host: str = "https://us.i.posthog.com"

    @property
    def is_tracing_enabled(self) -> bool:
        """是否开启链路追踪。两个 key 都配了才真正启用,避免半配置状态。"""
        return bool(self.langfuse_public_key and self.langfuse_secret_key)


@lru_cache
def get_settings() -> Settings:
    """全局唯一的配置实例。lru_cache 保证进程内只解析一次环境变量。"""
    return Settings()
