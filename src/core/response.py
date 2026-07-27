# =============================================================================
# 统一 API 响应结构
# =============================================================================

from __future__ import annotations

from typing import Any, Generic, Optional, TypeVar

from pydantic import BaseModel, Field

T = TypeVar("T")


class APIResponse(BaseModel, Generic[T]):
    """与接口契约一致的统一 JSON 响应。"""

    code: int = Field(default=200, description="业务状态码")
    message: str = Field(default="操作成功", description="提示信息")
    data: Optional[T] = Field(default=None, description="业务数据")


def ok(data: Any = None, message: str = "操作成功", code: int = 200) -> dict:
    """构造成功响应字典。"""
    return {"code": code, "message": message, "data": data}


def fail(message: str, code: int = 400, data: Any = None) -> dict:
    """构造失败响应字典。"""
    return {"code": code, "message": message, "data": data}