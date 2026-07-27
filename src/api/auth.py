# =============================================================================
# 认证接口：验证码 / 登录 / 登出
# =============================================================================

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.database import get_db_session
from src.core.logging_config import get_logger
from src.core.response import fail, ok
from src.models.entities import User
from src.schemas.auth import LoginRequest
from src.api.deps import get_current_user
from src.services.auth_service import login_user
from src.services.captcha_service import create_captcha

logger = get_logger(__name__)
router = APIRouter(prefix="/auth", tags=["auth"])


@router.get("/captcha")
async def get_captcha(session: AsyncSession = Depends(get_db_session)):
    """获取图形验证码。"""
    data = await create_captcha(session)
    return ok(data=data, message="操作成功")


@router.post("/login")
async def login(
    body: LoginRequest,
    session: AsyncSession = Depends(get_db_session),
):
    """用户名 + 密码 + 验证码登录。"""
    token_data, err = await login_user(
        session,
        username=body.username,
        password=body.password,
        captcha_id=body.captcha_id,
        captcha_code=body.captcha_code,
    )
    if err:
        # 1001 验证码；1002 账号密码
        code = 1001 if "验证码" in err else 1002
        return fail(message=err, code=400 if code else 400)
    return ok(data=token_data, message="登录成功")


@router.post("/logout")
async def logout(current_user: User = Depends(get_current_user)):
    """
    退出登录。

    当前为无状态 JWT，服务端记录日志即可；
    前端删除本地 Token 即完成注销。
    """
    logger.info("用户注销 user_id=%s username=%s", current_user.id, current_user.username)
    return ok(data=None, message="已成功注销")