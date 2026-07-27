# =============================================================================
# 认证相关 Schema
# =============================================================================

from __future__ import annotations

from pydantic import BaseModel, Field


class LoginRequest(BaseModel):
    """登录请求体。"""

    username: str = Field(..., min_length=1, max_length=50, description="用户名")
    password: str = Field(..., min_length=1, max_length=128, description="密码")
    captcha_id: str = Field(..., description="验证码 ID")
    captcha_code: str = Field(..., min_length=1, max_length=10, description="验证码字符")


class CaptchaData(BaseModel):
    """验证码响应数据。"""

    captcha_id: str
    image_base64: str
    fixed_code: str | None = Field(
        default=None, description="固定验证码时回传，供前端预填"
    )


class TokenData(BaseModel):
    """登录成功后的 Token 数据。"""

    access_token: str
    token_type: str = "bearer"
    expires_in: int