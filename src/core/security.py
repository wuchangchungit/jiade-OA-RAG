# =============================================================================
# 安全模块：密码哈希与 JWT 签发/校验
# =============================================================================

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from jose import JWTError, jwt
from passlib.context import CryptContext

from src.core.config import get_settings
from src.core.logging_config import get_logger

logger = get_logger(__name__)

# 使用 bcrypt 进行密码哈希
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
ALGORITHM = "HS256"


def hash_password(plain_password: str) -> str:
    """对明文密码进行哈希。"""
    return pwd_context.hash(plain_password)


def verify_password(plain_password: str, password_hash: str) -> bool:
    """校验明文密码与哈希是否匹配。"""
    try:
        return pwd_context.verify(plain_password, password_hash)
    except Exception as exc:  # noqa: BLE001
        logger.warning("密码校验异常: %s", exc)
        return False


def create_access_token(
    subject: str,
    extra_claims: Optional[dict[str, Any]] = None,
    expires_minutes: Optional[int] = None,
) -> tuple[str, int]:
    """
    签发 JWT。

    返回:
        (token, expires_in_seconds)
    """
    settings = get_settings()
    minutes = expires_minutes if expires_minutes is not None else settings.jwt_expire_minutes
    expire = datetime.now(timezone.utc) + timedelta(minutes=minutes)
    payload: dict[str, Any] = {"sub": subject, "exp": expire}
    if extra_claims:
        payload.update(extra_claims)
    token = jwt.encode(payload, settings.app_secret_key, algorithm=ALGORITHM)
    return token, minutes * 60


def decode_access_token(token: str) -> dict[str, Any]:
    """
    解码并校验 JWT。

    失败时抛出 JWTError。
    """
    settings = get_settings()
    return jwt.decode(token, settings.app_secret_key, algorithms=[ALGORITHM])