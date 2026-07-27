# =============================================================================
# 认证服务：登录校验、演示账号初始化
# =============================================================================

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.config import get_settings
from src.core.logging_config import get_logger
from src.core.security import create_access_token, hash_password, verify_password
from src.models.entities import User
from src.services.captcha_service import verify_captcha

logger = get_logger(__name__)


async def ensure_demo_user(session: AsyncSession) -> None:
    """若不存在演示账号，则自动创建（仅便于本地联调）。"""
    settings = get_settings()
    result = await session.execute(
        select(User).where(User.username == settings.demo_username)
    )
    user = result.scalar_one_or_none()
    if user is not None:
        return
    user = User(
        username=settings.demo_username,
        password_hash=hash_password(settings.demo_password),
        status=1,
    )
    session.add(user)
    await session.commit()
    logger.info("已初始化演示账号: %s", settings.demo_username)


async def login_user(
    session: AsyncSession,
    username: str,
    password: str,
    captcha_id: str,
    captcha_code: str,
) -> tuple[dict | None, str]:
    """
    执行登录。

    返回:
        (token_data, error_message)
        成功时 error_message 为空字符串。
    """
    # 1) 验证码
    captcha_ok = await verify_captcha(session, captcha_id, captcha_code)
    if not captcha_ok:
        return None, "验证码错误或已过期"

    # 2) 用户凭证
    result = await session.execute(select(User).where(User.username == username))
    user = result.scalar_one_or_none()
    if user is None or user.status != 1:
        return None, "用户名或密码错误"
    if not verify_password(password, user.password_hash):
        return None, "用户名或密码错误"

    token, expires_in = create_access_token(
        subject=str(user.id),
        extra_claims={"username": user.username},
    )
    logger.info("用户登录成功 user_id=%s username=%s", user.id, user.username)
    return {
        "access_token": token,
        "token_type": "bearer",
        "expires_in": expires_in,
    }, ""