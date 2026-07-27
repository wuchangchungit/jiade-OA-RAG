# =============================================================================
# 对话服务：会话创建、历史加载、消息持久化、SSE 编排
# =============================================================================

from __future__ import annotations

import json
import uuid
from typing import Any, AsyncIterator

from langchain_core.messages import AIMessage, HumanMessage
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.agent.graph import run_agent_stream
from src.core.logging_config import get_logger
from src.models.entities import ChatMessage, ChatSession

logger = get_logger(__name__)


async def create_session(session: AsyncSession, user_id: int) -> str:
    """创建新的多轮对话会话。"""
    session_id = f"sess_{uuid.uuid4()}"
    row = ChatSession(session_id=session_id, user_id=user_id, title="新对话")
    session.add(row)
    await session.commit()
    logger.info("创建会话 session_id=%s user_id=%s", session_id, user_id)
    return session_id


async def ensure_session_owner(
    session: AsyncSession,
    session_id: str,
    user_id: int,
) -> ChatSession:
    """校验会话存在且归属当前用户。"""
    result = await session.execute(
        select(ChatSession).where(
            ChatSession.session_id == session_id,
            ChatSession.is_deleted.is_(False),
        )
    )
    row = result.scalar_one_or_none()
    if row is None:
        raise ValueError("会话不存在")
    if row.user_id != user_id:
        raise PermissionError("无权访问该会话")
    return row


async def load_history_messages(
    session: AsyncSession,
    session_id: str,
    limit: int = 20,
) -> list:
    """从数据库加载历史消息，转换为 LangChain Message。"""
    result = await session.execute(
        select(ChatMessage)
        .where(ChatMessage.session_id == session_id)
        .order_by(ChatMessage.created_at.asc())
        .limit(limit)
    )
    rows = result.scalars().all()
    messages = []
    for row in rows:
        if row.role == "user":
            messages.append(HumanMessage(content=row.content))
        elif row.role == "assistant":
            messages.append(AIMessage(content=row.content))
    return messages


async def save_message(
    session: AsyncSession,
    *,
    session_id: str,
    role: str,
    content: str,
    tool_calls: dict | None = None,
) -> None:
    """持久化一条对话消息。"""
    row = ChatMessage(
        session_id=session_id,
        role=role,
        content=content,
        tool_calls=tool_calls,
    )
    session.add(row)
    await session.commit()


async def stream_chat(
    session: AsyncSession,
    *,
    session_id: str,
    user_id: int,
    message: str,
) -> AsyncIterator[dict[str, Any]]:
    """
    编排多轮流式对话：校验会话、加载历史、运行 Agent、落库。
    """
    await ensure_session_owner(session, session_id, user_id)
    await save_message(session, session_id=session_id, role="user", content=message)

    history = await load_history_messages(session, session_id, limit=20)
    # 去掉刚刚写入的最后一条 user，避免与 initial_state 重复
    if history and isinstance(history[-1], HumanMessage):
        history = history[:-1]

    answer_parts: list[str] = []
    async for evt in run_agent_stream(
        session_id=session_id,
        user_id=user_id,
        user_query=message,
        history_messages=history,
    ):
        if evt.get("event") == "token":
            answer_parts.append((evt.get("data") or {}).get("content") or "")
        if evt.get("event") == "done":
            answer = "".join(answer_parts).strip()
            data = evt.get("data") or {}
            if not answer:
                answer = data.get("answer") or ""
            if answer:
                await save_message(
                    session,
                    session_id=session_id,
                    role="assistant",
                    content=answer,
                )
            # 若首条消息，用用户问题更新会话标题
            chat = await ensure_session_owner(session, session_id, user_id)
            if chat.title == "新对话":
                chat.title = message[:50]
                await session.commit()
        yield evt


def format_sse(event: str, data: dict) -> str:
    """格式化为 SSE 文本帧。"""
    payload = json.dumps(data, ensure_ascii=False)
    return f"event: {event}\ndata: {payload}\n\n"