# =============================================================================
# LangGraph Agent 工作流：决策 / 工具调用 / 降级 / 流式输出
# =============================================================================

from __future__ import annotations

import asyncio
import json
from typing import Any, AsyncIterator, Optional

from langchain_core.messages import (
    AIMessage,
    HumanMessage,
    SystemMessage,
    ToolMessage,
)
from langchain_openai import ChatOpenAI
from langgraph.graph import END, StateGraph
from langgraph.prebuilt import ToolNode

from src.agent.prompts import (
    FALLBACK_SYSTEM_HINT,
    build_system_prompt,
    format_chat_history,
    truncate_query,
    wrap_retrieved_context,
)
from src.agent.state import AgentState
from src.core.config import get_settings
from src.core.logging_config import get_logger
from src.tools.ems_handbook_tool import ems_handbook_tool

logger = get_logger(__name__)


def _build_llm(streaming: bool = True) -> ChatOpenAI:
    """构建 ChatOpenAI 客户端。"""
    settings = get_settings()
    return ChatOpenAI(
        model=settings.llm_model_name,
        api_key=settings.openai_api_key or "EMPTY",
        base_url=settings.openai_api_base,
        temperature=0.2,
        streaming=streaming,
        timeout=60.0,
        max_retries=2,
    )


def should_continue(state: AgentState) -> str:
    """
    条件边：决定下一步走向。
    - call_ems_tool: 调用 RAG 工具
    - trigger_fallback: 超限或错误，进入一次性降级生成
    - finish: 结束本轮
    """
    messages = state["messages"]
    last_message = messages[-1] if messages else None
    tool_call_count = state.get("tool_call_count", 0)
    max_tool_calls = state.get("max_tool_calls", 3)

    if state.get("error_flag", False):
        return "trigger_fallback"

    if last_message is not None and getattr(last_message, "tool_calls", None):
        if tool_call_count < max_tool_calls:
            return "call_ems_tool"
        # 超过上限：降级一次后结束，避免 fallback <-> router 死循环
        return "trigger_fallback"

    return "finish"


def _collect_lc_messages(state: AgentState, with_tools_hint: bool = True) -> list:
    """组装发给 LLM 的消息列表。"""
    settings = get_settings()
    query = truncate_query(state.get("current_query", ""), settings.user_query_max_chars)
    history_text = format_chat_history(
        list(state.get("messages") or [])[:-1],
        max_rounds=settings.chat_history_window,
    )
    tool_desc = (
        "ems_handbook_tool(query: str): 检索公司员工手册、规章制度及新材料相关知识库"
        if with_tools_hint
        else "（当前已禁用工具，请直接作答）"
    )
    system_prompt = build_system_prompt(
        user_info=f"user_id={state.get('user_id')}",
        chat_history=history_text,
        user_query=query,
        tool_descriptions=tool_desc,
    )
    lc_messages: list = [SystemMessage(content=system_prompt)]
    for msg in state.get("messages") or []:
        lc_messages.append(msg)
    retrieved = state.get("retrieved_context")
    if retrieved:
        lc_messages.append(
            SystemMessage(
                content="以下是知识库检索结果，请优先依据其回答：\n"
                + wrap_retrieved_context(retrieved)
            )
        )
    return lc_messages


def build_agent_graph():
    """构建并编译 LangGraph 状态图。"""
    tools = [ems_handbook_tool]
    llm = _build_llm(streaming=True)
    llm_with_tools = llm.bind_tools(tools)
    llm_no_tools = _build_llm(streaming=True)
    tool_node = ToolNode(tools)

    async def agent_router_node(state: AgentState) -> dict[str, Any]:
        """LLM 决策节点：判断是否调用工具或直接回答。"""
        lc_messages = _collect_lc_messages(state, with_tools_hint=True)
        logger.info(
            "agent_router 推理开始 session=%s tool_count=%s",
            state.get("session_id"),
            state.get("tool_call_count"),
        )
        try:
            ai_message = await asyncio.wait_for(
                llm_with_tools.ainvoke(lc_messages), timeout=90.0
            )
            return {"messages": [ai_message], "error_flag": False}
        except asyncio.TimeoutError:
            logger.error("agent_router LLM 调用超时")
            return {
                "messages": [AIMessage(content="模型响应超时，请稍后重试。")],
                "error_flag": False,
                "is_finished": True,
            }
        except Exception as exc:  # noqa: BLE001
            logger.exception("agent_router LLM 调用失败: %s", exc)
            return {
                "messages": [AIMessage(content="模型服务暂时不可用，请稍后重试。")],
                "error_flag": False,
                "is_finished": True,
            }

    async def ems_handbook_tool_node(state: AgentState) -> dict[str, Any]:
        """RAG 工具执行节点（含超时与上下文提取）。"""
        last = state["messages"][-1]
        tool_calls = getattr(last, "tool_calls", None) or []
        if not tool_calls:
            return {"error_flag": True}

        query = ""
        for tc in tool_calls:
            if tc.get("name") == "ems_handbook_tool":
                query = (tc.get("args") or {}).get("query", "")
                break

        # 重复 query 检测：与最近 ToolMessage 内容比对
        for msg in reversed(list(state.get("messages") or [])):
            if isinstance(msg, ToolMessage):
                if query and query in str(msg.content):
                    logger.info("检测到重复检索 query，复用缓存结果")
                    return {
                        "messages": [
                            ToolMessage(
                                content=msg.content,
                                tool_call_id=tool_calls[0]["id"],
                                name="ems_handbook_tool",
                            )
                        ],
                        "retrieved_context": state.get("retrieved_context"),
                        "tool_call_count": state.get("tool_call_count", 0) + 1,
                        "error_flag": False,
                    }
                break

        logger.info("执行 ems_handbook_tool，query=%s", query[:120])
        tool_timeout = float(get_settings().rag_tool_timeout_seconds)
        try:
            result_state = await asyncio.wait_for(
                tool_node.ainvoke(state), timeout=tool_timeout
            )
        except asyncio.TimeoutError:
            logger.error("ems_handbook_tool 执行超时（%.1fs）", tool_timeout)
            tool_msg = ToolMessage(
                content=json.dumps(
                    {
                        "status": "error",
                        "message": "检索工具响应超时，未能获取相关资料",
                        "retrieved_nodes": [],
                    },
                    ensure_ascii=False,
                ),
                tool_call_id=tool_calls[0]["id"],
                name="ems_handbook_tool",
            )
            return {
                "messages": [tool_msg],
                "retrieved_context": "检索工具响应超时，未能获取相关资料",
                "tool_call_count": state.get("tool_call_count", 0) + 1,
                "error_flag": False,
            }
        except Exception as exc:  # noqa: BLE001
            logger.exception("ems_handbook_tool 执行异常: %s", exc)
            tool_msg = ToolMessage(
                content=json.dumps(
                    {"status": "error", "message": str(exc), "retrieved_nodes": []},
                    ensure_ascii=False,
                ),
                tool_call_id=tool_calls[0]["id"],
                name="ems_handbook_tool",
            )
            return {
                "messages": [tool_msg],
                "tool_call_count": state.get("tool_call_count", 0) + 1,
                "error_flag": False,
            }

        retrieved_context = state.get("retrieved_context")
        new_messages = result_state.get("messages") or []
        for msg in new_messages:
            if isinstance(msg, ToolMessage):
                try:
                    payload = json.loads(msg.content)
                    retrieved_context = payload.get("retrieved_context") or (
                        "\n\n".join(
                            n.get("text", "") for n in (payload.get("retrieved_nodes") or [])
                        )
                        or "未检索到相关文档内容"
                    )
                except Exception:  # noqa: BLE001
                    retrieved_context = str(msg.content)[:2000]

        return {
            "messages": new_messages,
            "retrieved_context": retrieved_context,
            "tool_call_count": state.get("tool_call_count", 0) + 1,
            "error_flag": False,
        }

    async def fallback_node(state: AgentState) -> dict[str, Any]:
        """
        降级节点：禁用工具，直接生成最终回答，然后结束。
        """
        logger.warning(
            "进入 fallback_node session=%s count=%s",
            state.get("session_id"),
            state.get("tool_call_count"),
        )
        lc_messages = _collect_lc_messages(state, with_tools_hint=False)
        lc_messages.append(SystemMessage(content=FALLBACK_SYSTEM_HINT))
        try:
            ai_message = await asyncio.wait_for(
                llm_no_tools.ainvoke(lc_messages), timeout=90.0
            )
        except asyncio.TimeoutError:
            logger.error("fallback LLM 调用超时")
            ai_message = AIMessage(content="模型响应超时，请稍后重试。")
        except Exception as exc:  # noqa: BLE001
            logger.exception("fallback LLM 失败: %s", exc)
            ai_message = AIMessage(
                content="当前无法完成知识库检索，请稍后重试或换一种提问方式。"
            )
        return {
            "messages": [ai_message],
            "error_flag": False,
            "is_finished": True,
        }

    async def finish_node(state: AgentState) -> dict[str, Any]:
        """结束节点：标记本轮完成。"""
        return {"is_finished": True}

    graph = StateGraph(AgentState)
    graph.add_node("agent_router", agent_router_node)
    graph.add_node("ems_tool", ems_handbook_tool_node)
    graph.add_node("fallback", fallback_node)
    graph.add_node("finish", finish_node)

    graph.set_entry_point("agent_router")
    graph.add_conditional_edges(
        "agent_router",
        should_continue,
        {
            "call_ems_tool": "ems_tool",
            "trigger_fallback": "fallback",
            "finish": "finish",
        },
    )
    graph.add_edge("ems_tool", "agent_router")
    # 降级节点直接结束，避免死循环
    graph.add_edge("fallback", "finish")
    graph.add_edge("finish", END)
    return graph.compile()


_compiled_graph = None


def get_agent_graph():
    """获取编译后的 Agent 图单例。"""
    global _compiled_graph
    if _compiled_graph is None:
        _compiled_graph = build_agent_graph()
        logger.info("LangGraph Agent 图已编译")
    return _compiled_graph


async def run_agent_stream(
    *,
    session_id: str,
    user_id: int,
    user_query: str,
    history_messages: Optional[list] = None,
) -> AsyncIterator[dict[str, Any]]:
    """
    异步运行 Agent，并产出 SSE 事件字典。

    事件类型: tool_start / tool_end / token / error / done
    """
    settings = get_settings()
    query = truncate_query(user_query, settings.user_query_max_chars)
    history_messages = history_messages or []

    initial_state: AgentState = {
        "messages": list(history_messages) + [HumanMessage(content=query)],
        "session_id": session_id,
        "user_id": user_id,
        "current_query": query,
        "tool_call_count": 0,
        "max_tool_calls": settings.max_tool_calls,
        "retrieved_context": None,
        "error_flag": False,
        "is_finished": False,
    }

    graph = get_agent_graph()
    final_answer_parts: list[str] = []
    saw_tool = False

    try:
        async for event in graph.astream_events(initial_state, version="v2"):
            kind = event.get("event")
            name = str(event.get("name", ""))
            data = event.get("data") or {}

            if kind == "on_tool_start" and "ems_handbook" in name:
                saw_tool = True
                inputs = data.get("input") or {}
                tool_query = ""
                if isinstance(inputs, dict):
                    tool_query = inputs.get("query") or ""
                    if not tool_query and isinstance(inputs.get("input"), str):
                        tool_query = inputs.get("input")
                yield {
                    "event": "tool_start",
                    "data": {
                        "tool": "ems_handbook_tool",
                        "query": tool_query or query,
                    },
                }

            elif kind == "on_tool_end" and "ems_handbook" in name:
                yield {
                    "event": "tool_end",
                    "data": {"tool": "ems_handbook_tool", "status": "success"},
                }

            elif kind == "on_chat_model_stream":
                chunk = data.get("chunk")
                if chunk is None:
                    continue
                # 跳过工具调用阶段的空/片段
                if getattr(chunk, "tool_call_chunks", None):
                    continue
                content = getattr(chunk, "content", None)
                if content:
                    final_answer_parts.append(content)
                    yield {"event": "token", "data": {"content": content}}

        final_answer = "".join(final_answer_parts).strip()

        # 兜底：若未捕获到流式 token，则从最终状态提取 AIMessage（不再次跑图）
        if not final_answer:
            # 使用 updates 模式取最后状态中的消息代价高；改为同步再取一次 values
            # 这里仅读取已缓存图状态不可行，故做轻量 ainvoke 仅当完全无输出
            logger.warning(
                "未捕获到流式 token，执行一次 ainvoke 兜底 session=%s saw_tool=%s",
                session_id,
                saw_tool,
            )
            final_state = await graph.ainvoke(initial_state)
            for msg in reversed(final_state.get("messages") or []):
                if isinstance(msg, AIMessage) and msg.content and not getattr(msg, "tool_calls", None):
                    final_answer = str(msg.content)
                    step = 32
                    for i in range(0, len(final_answer), step):
                        yield {"event": "token", "data": {"content": final_answer[i : i + step]}}
                        await asyncio.sleep(0)
                    break

        yield {
            "event": "done",
            "data": {
                "session_id": session_id,
                "finish_reason": "stop",
                "answer": final_answer,
            },
        }
    except Exception as exc:  # noqa: BLE001
        logger.exception("Agent 流式运行异常: %s", exc)
        yield {"event": "error", "data": {"error_code": 3001, "message": str(exc)}}
        yield {
            "event": "done",
            "data": {"session_id": session_id, "finish_reason": "error"},
        }