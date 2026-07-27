# =============================================================================
# ems_handbook_tool
# 将 RAG 混合检索流水线封装为符合 LangGraph / LangChain Tool 规范的工具
# =============================================================================

from __future__ import annotations

import json
from typing import Any, Optional

from langchain_core.tools import StructuredTool
from pydantic import BaseModel, Field

from src.core.logging_config import get_logger
from src.rag.pipeline import RAGPipeline, get_rag_pipeline

logger = get_logger(__name__)


class EMSHandbookInput(BaseModel):
    """ems_handbook_tool 的输入 Schema，与接口契约保持一致。"""

    query: str = Field(
        ...,
        description="针对员工手册或新材料相关文档的检索关键词或自然语言问题",
    )


def _run_ems_handbook_search(
    query: str,
    pipeline: Optional[RAGPipeline] = None,
) -> str:
    """
    执行 RAG 检索并返回 JSON 字符串。

    LangGraph / LangChain 工具通常要求返回 str，
    因此将契约字典序列化为 JSON，便于后续节点解析。
    """
    logger.info("ems_handbook_tool 被调用，query=%s", query[:200])
    rag = pipeline or get_rag_pipeline()

    try:
        result: dict[str, Any] = rag.search(query)
        if result.get("status") == "success":
            # 基于本次检索结果直接拼装上下文，避免重复检索
            nodes = result.get("retrieved_nodes") or []
            if not nodes:
                result["retrieved_context"] = "未检索到相关文档内容"
            else:
                blocks = []
                for idx, item in enumerate(nodes, start=1):
                    meta = item.get("metadata") or {}
                    file_name = meta.get("file_name") or "unknown"
                    score = item.get("score", 0.0)
                    text_body = item.get("text", "")
                    blocks.append(
                        f"[片段 {idx}] 来源文件: {file_name} | 相关度: {score:.4f}\n{text_body}"
                    )
                result["retrieved_context"] = "\n\n".join(blocks)
        payload = json.dumps(result, ensure_ascii=False)
        node_count = len(result.get("retrieved_nodes") or [])
        logger.info(
            "ems_handbook_tool 执行完成，status=%s，nodes=%d",
            result.get("status"),
            node_count,
        )
        return payload
    except Exception as exc:  # noqa: BLE001
        logger.exception("ems_handbook_tool 执行异常: %s", exc)
        error_payload = {
            "status": "error",
            "error_code": "2002",
            "message": str(exc),
            "retrieved_nodes": [],
            "retrieved_context": "未检索到相关文档内容",
        }
        return json.dumps(error_payload, ensure_ascii=False)


def create_ems_handbook_tool(
    pipeline: Optional[RAGPipeline] = None,
) -> StructuredTool:
    """
    创建名为 ems_handbook_tool 的 LangChain StructuredTool。

    可注入自定义 RAGPipeline（便于单测）；默认使用全局单例。
    """

    def _invoke(query: str) -> str:
        return _run_ems_handbook_search(query=query, pipeline=pipeline)

    tool = StructuredTool.from_function(
        func=_invoke,
        name="ems_handbook_tool",
        description=(
            "检索公司员工手册、规章制度及新材料相关知识库。"
            "当用户问题涉及制度流程、产品规格、操作手册等专业内容时，"
            "应优先调用本工具获取参考资料，避免凭空编造。"
        ),
        args_schema=EMSHandbookInput,
        return_direct=False,
    )
    logger.info("已创建 LangGraph 工具: ems_handbook_tool")
    return tool


# 模块级默认工具实例：名称必须为 ems_handbook_tool，供 Agent 直接 import
ems_handbook_tool: StructuredTool = create_ems_handbook_tool()


def ems_handbook_tool_func(query: str) -> str:
    """函数形式的工具入口（便于测试与二次封装）。"""
    return _run_ems_handbook_search(query=query)


__all__ = [
    "EMSHandbookInput",
    "ems_handbook_tool",
    "create_ems_handbook_tool",
    "ems_handbook_tool_func",
]