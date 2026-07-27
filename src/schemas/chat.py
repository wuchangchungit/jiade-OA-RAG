# =============================================================================
# 对话相关 Schema
# =============================================================================

from __future__ import annotations

from pydantic import BaseModel, Field


class NewSessionData(BaseModel):
    """新建会话响应。"""

    session_id: str


class ChatStreamRequest(BaseModel):
    """流式对话请求体。"""

    session_id: str = Field(..., description="会话 ID")
    message: str = Field(..., min_length=1, description="用户当前轮输入")