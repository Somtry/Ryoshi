"""BYOK 用户密钥加解密(Fernet 对称加密)。

设计意图:
    用户在设置页填的 API key 绝不明文落库;这里提供一对加解密原语,
    写入时加密成 base64url 字符串,读取时解密回明文,再喂给 LangChain 客户端。

    密钥来源优先级:
      1. BYOK_ENCRYPTION_KEY 环境变量(生产必须显式配置)
      2. 开发兜底:~/.ryoshi/dev-key 文件(首次启动时随机生成,机器间隔离)

    Fernet 自带 HMAC 完整性校验,密文被篡改会解密失败(InvalidToken),
    调用方应把它当"密钥不可用"处理(回退到环境变量,或提示用户重配)。
"""

import logging
from pathlib import Path

from cryptography.fernet import Fernet, InvalidToken

from ryoshi.config import get_settings

logger = logging.getLogger("ryoshi.crypto")

# 模块级缓存:避免每次加解密都重新构造 Fernet 实例
_fernet_instance: Fernet | None = None
_fernet_warned = False


class CryptoError(Exception):
    """密钥配置或加解密失败。"""


def _get_dev_key_file() -> Path:
    """开发模式密钥文件路径(~/.ryoshi/dev-key)。"""
    return Path.home() / ".ryoshi" / "dev-key"


def _load_or_generate_dev_key() -> bytes:
    """开发环境密钥:从本地文件读取,不存在则生成。

    与之前 sha256(environment+anonymous_user_id) 的方案不同,
    这个密钥是随机生成的,不同机器/部署之间不通用,
    即使数据库泄露也无法推导出其他环境的密钥。
    """
    key_file = _get_dev_key_file()

    # 已存在则读取
    if key_file.exists():
        raw = key_file.read_bytes()
        # 校验长度(Fernet key 是 32 字节 base64url 编码后 44 字符)
        if len(raw) == 44:
            return raw
        logger.warning("开发密钥文件损坏,重新生成")

    # 生成新密钥
    key = Fernet.generate_key()
    key_file.parent.mkdir(parents=True, exist_ok=True)
    key_file.write_bytes(key)
    # 限制文件权限(仅当前用户可读)
    key_file.chmod(0o600)
    logger.info(f"已生成开发用 BYOK 密钥: {key_file}")
    return key


def _fernet() -> Fernet:
    """取 Fernet 实例(带模块级缓存)。"""
    global _fernet_instance, _fernet_warned

    s = get_settings()
    raw = s.byok_encryption_key.strip()

    # 生产环境:必须显式配置
    if raw:
        if _fernet_instance is None:
            try:
                _fernet_instance = Fernet(raw.encode())
            except (ValueError, InvalidToken) as exc:
                raise CryptoError(
                    "BYOK_ENCRYPTION_KEY 不是合法的 Fernet key(应为 base64url 32 字节)。"
                    " 用 `python -c \"from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())\"` 生成。"
                ) from exc
        return _fernet_instance

    # 开发环境:用本地文件密钥(机器间隔离)
    if not _fernet_warned:
        logger.warning(
            "BYOK_ENCRYPTION_KEY 未配置,使用本地开发密钥(~/.ryoshi/dev-key);"
            "生产环境必须显式配置。"
        )
        _fernet_warned = True

    if _fernet_instance is None:
        _fernet_instance = Fernet(_load_or_generate_dev_key())
    return _fernet_instance


def encrypt_api_key(plaintext: str) -> str:
    """把明文 API key 加密成 base64url 字符串(可安全落库)。"""
    if not plaintext:
        raise CryptoError("不能加密空密钥")
    return _fernet().encrypt(plaintext.encode()).decode()


def decrypt_api_key(token: str) -> str:
    """把数据库里的密文解回明文。密文损坏/密钥不匹配抛 CryptoError。"""
    try:
        return _fernet().decrypt(token.encode()).decode()
    except (InvalidToken, ValueError) as exc:
        raise CryptoError(
            "无法解密该密钥(可能是 BYOK_ENCRYPTION_KEY 变更或密文损坏),请重新配置。"
        ) from exc


def mask_api_key(plaintext: str) -> str:
    """用于在 API 响应里回显的掩码形式(只露尾号,便于用户辨认)。

    不泄露密钥长度:统一显示 8 个掩码字符 + 最后 4 位。
    """
    if len(plaintext) <= 4:
        return "••••••••"
    return f"••••••••{plaintext[-4:]}"
