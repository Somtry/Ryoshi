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

from fastapi import APIRouter, Depends, Form, Header, HTTPException, Request, UploadFile
from sqlalchemy.ext.asyncio import AsyncSession

from ryoshi.auth import resolve_user
from ryoshi.config import get_settings
from ryoshi.db.engine import get_session
from ryoshi.db.models import LibraryFile

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
    request: Request,
    file: UploadFile,
    chatId: str = Form(...),
    authorization: str | None = Header(None),
    session: AsyncSession = Depends(get_session),
):
    """接收 multipart 文件,存到对象存储,返回 {success, file: {...}}。

    对应原项目 app/api/upload/route.ts。返回的 file 对象包含:
    url/key/mediaType/filename/size + 可选 id/libraryFile(登录用户写库后返回)。
    """
    s = get_settings()
    # 认证:ENABLE_AUTH=false 时匿名;ENABLE_AUTH=true 时校验 JWT
    user = await resolve_user(authorization, allow_anonymous_fallback=True)
    user_id = user.id

    # 限流(仅云端部署生效):按 IP 每天 50 次,防匿名刷 5MB 文件进 S3
    from ryoshi.ratelimit import check_upload_limit, client_ip_from_request

    client_ip = client_ip_from_request(request)
    if client_ip:
        limit_result = await check_upload_limit(client_ip)
        if not limit_result.allowed:
            raise HTTPException(
                status_code=429,
                detail="上传过于频繁,请明天再试。",
            )

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
    except ImportError as exc:
        raise HTTPException(
            status_code=503,
            detail="aioboto3 not installed. Run: uv add aioboto3",
        ) from exc

    async with aioboto3.Session().client("s3", **_s3_config()) as s3:
        await s3.put_object(
            Bucket=bucket,
            Key=key,
            Body=data,
            ContentType=media_type,
        )

    public_url = s.r2_public_url or f"{_s3_config()['endpoint_url'].rstrip('/')}/{bucket}"
    file_url = f"{public_url.rstrip('/')}/{key}"

    # 登录用户写库(对应原项目 createLibraryFile);匿名用户跳过
    library_file = None
    if not user.is_anonymous:
        library_file = LibraryFile(
            id=uuid.uuid4().hex[:24],
            user_id=user_id,
            chat_id=chatId,
            filename=file.filename or "file",
            object_key=key,
            media_type=media_type,
            size=len(data),
        )
        session.add(library_file)
        await session.commit()

    # 响应形状与原型一致: {success: true, file: {...}}
    # 前端 chat-panel 按此解构,需要 id/libraryFile/size 字段
    result: dict = {
        "url": file_url,
        "key": key,
        "mediaType": media_type,
        "filename": file.filename or "file",
        "size": len(data),
    }
    if library_file:
        result["id"] = library_file.id
        result["libraryFile"] = {
            "id": library_file.id,
            "filename": library_file.filename,
            "objectKey": library_file.object_key,
            "mediaType": library_file.media_type,
            "size": library_file.size,
            "key": library_file.object_key,
            "url": file_url,
            "createdAt": library_file.created_at.isoformat() if library_file.created_at else None,
        }

    return {"success": True, "file": result}
