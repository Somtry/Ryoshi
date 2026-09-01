"""文件上传路由:POST /api/upload。

设计意图:
    对应原项目 app/api/upload/route.ts。把用户上传的附件(图片/PDF)
    存到 S3 兼容对象存储(Cloudflare R2 / AWS S3 / MinIO),返回可访问的 URL。

    关键设计:
      - 文件类型按魔数(magic bytes)校验,不信任浏览器报的 Content-Type
      - 未配置对象存储时返回 503 + 明确错误信息,前端据此隐藏上传入口
      - 大小上限 5MB(与原项目一致)
      - 用 aioboto3(异步 boto3)走标准 S3 API,签名/重试由 SDK 处理
"""

import uuid

from fastapi import APIRouter, Form, Header, HTTPException, UploadFile

from ryoshi.auth import resolve_user
from ryoshi.config import get_settings

router = APIRouter(prefix="/api", tags=["upload"])

MAX_FILE_SIZE = 5 * 1024 * 1024  # 5MB,与原项目一致

# 支持的文件类型与魔数(对应原项目 file-signature.ts)
_ALLOWED_TYPES = {
    "image/jpeg": lambda b: b[:3] == b"\xff\xd8\xff",
    "image/png": lambda b: b[:8] == b"\x89PNG\r\n\x1a\n",
    "application/pdf": lambda b: b"%PDF-" in b[:1024],
}


def _detect_media_type(data: bytes) -> str | None:
    """按魔数识别真实文件类型(不信任浏览器 Content-Type)。"""
    for media_type, check in _ALLOWED_TYPES.items():
        if check(data):
            return media_type
    return None


def _is_storage_configured() -> bool:
    """对象存储是否已配置(R2_ACCOUNT_ID+密钥,或 S3_ENDPOINT+密钥)。"""
    s = get_settings()
    has_keys = bool(s.r2_access_key_id and s.r2_secret_access_key)
    has_endpoint = bool(s.r2_account_id or s.s3_endpoint)
    return has_keys and has_endpoint


def _s3_config() -> dict:
    """组装 aioboto3 的 S3 客户端配置。"""
    s = get_settings()
    endpoint = s.s3_endpoint or f"https://{s.r2_account_id}.r2.cloudflarestorage.com"
    return {
        "endpoint_url": endpoint,
        "aws_access_key_id": s.r2_access_key_id,
        "aws_secret_access_key": s.r2_secret_access_key,
        "region_name": "auto",  # R2 用 auto
    }


def _object_key(user_id: str, chat_id: str, filename: str) -> str:
    """生成对象存储 key。格式: users/<uid>/<chatId>/<uuid>-<filename>"""
    safe_name = filename.replace("/", "_")[:200]
    return f"users/{user_id}/{chat_id}/{uuid.uuid4().hex[:8]}-{safe_name}"


@router.post("/upload")
async def upload_file(
    file: UploadFile,
    chatId: str = Form(...),
    authorization: str | None = Header(None),
):
    """接收 multipart 文件,存到对象存储,返回 {url, key, mediaType, filename}。"""
    s = get_settings()
    # 认证:ENABLE_AUTH=false 时匿名;ENABLE_AUTH=true 时校验 JWT
    user_id = resolve_user(authorization, allow_anonymous_fallback=True).id

    if not _is_storage_configured():
        raise HTTPException(
            status_code=503,
            detail="File upload storage is not configured. Set R2_ACCESS_KEY_ID, R2_SECRET_ACCESS_KEY, and either R2_ACCOUNT_ID or S3_ENDPOINT.",
        )

    data = await file.read()
    if len(data) > MAX_FILE_SIZE:
        raise HTTPException(status_code=400, detail="File too large (max 5MB)")

    media_type = _detect_media_type(data)
    if not media_type:
        raise HTTPException(status_code=400, detail="Unsupported file type")

    key = _object_key(user_id, chatId, file.filename or "file")
    bucket = s.r2_bucket_name or "user-uploads"

    # 上传到 S3 兼容存储(标准 PutObject,签名由 aioboto3 处理)
    try:
        import aioboto3
    except ImportError:
        raise HTTPException(
            status_code=503,
            detail="aioboto3 not installed. Run: uv add aioboto3",
        )

    async with aioboto3.Session().client("s3", **_s3_config()) as s3:
        await s3.put_object(
            Bucket=bucket,
            Key=key,
            Body=data,
            ContentType=media_type,
        )

    public_url = s.r2_public_url or f"{_s3_config()['endpoint_url'].rstrip('/')}/{bucket}"
    return {
        "url": f"{public_url.rstrip('/')}/{key}",
        "key": key,
        "mediaType": media_type,
        "filename": file.filename or "file",
    }
