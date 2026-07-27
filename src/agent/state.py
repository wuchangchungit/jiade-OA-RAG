# =============================================================================
# LangGraph Agent 全局状态定义
# =============================================================================

from __future__ import annotations

import operator
from typing import Annotated, Optional, Sequence, TypedDict

from langchain_core.messages import BaseMessage


class AgentState(TypedDict):
    """
    LangGraph Agent 全局状态模型。
    messages 使用 operator.add 追加合并。
    """

    messages: Annotated[Sequence[BaseMessage], operator.add]
    session_id: str
    user_id: int
    current_query: str
    tool_call_count: int
    max_tool_calls: int
    retrieved_context: Optional[str]
    error_flag: bool
    is_finished: bool