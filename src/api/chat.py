# =============================================================================
# 多轮对话接口：新建会话 / SSE 流式对话
# =============================================================================

from __future__ import annotations

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.deps import get_current_user
from src.core.database import get_db_session
from src.core.logging_config import get_logger
from src.core.response import fail, ok
from src.models.entities import User
from src.schemas.chat import ChatStreamRequest
from src.services.chat_service import create_session, format_sse, stream_chat

logger = get_logger(__name__)
router = APIRouter(prefix="/chat", tags=["chat"])


@router.post("/session/new")
async def new_session(
    session: AsyncSession = Depends(get_db_session),
    current_user: User = Depends(get_current_user),
):
    """创建新对话会话。"""
    session_id = await create_session(session, current_user.id)
    return ok(data={"session_id": session_id}, message="操作成功")


@router.post("/stream")
async def chat_stream(
    body: ChatStreamRequest,
    session: AsyncSession = Depends(get_db_session),
    current_user: User = Depends(get_current_user),
):
    """异步流式多轮对话（SSE）。"""
    if not body.message or not body.message.strip():
        return fail(message="消息不能为空", code=400)

    async def event_generator():
        try:
            async for evt in stream_chat(
                session,
                session_id=body.session_id,
                user_id=current_user.id,
                message=body.message.strip(),
            ):
                yield format_sse(evt["event"], evt.get("data") or {})
        except PermissionError as exc:
            yield format_sse("error", {"error_code": 401, "message": str(exc)})
            yield format_sse(
                "done",
                {"session_id": body.session_id, "finish_reason": "error"},
            )
        except ValueError as exc:
            yield format_sse("error", {"error_code": 400, "message": str(exc)})
            yield format_sse(
                "done",
                {"session_id": body.session_id, "finish_reason": "error"},
            )
        except Exception as exc:  # noqa: BLE001
            logger.exception("SSE 对话异常: %s", exc)
            yield format_sse(
                "error",
                {"error_code": 3001, "message": str(exc)},
            )
            yield format_sse(
                "done",
                {"session_id": body.session_id, "finish_reason": "error"},
            )

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )