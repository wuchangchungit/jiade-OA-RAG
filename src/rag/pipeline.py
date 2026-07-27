# =============================================================================
# RAG 流水线门面
# 统一封装：索引构建、增量入库、混合检索，供工具层与后续 API 调用
# =============================================================================

from __future__ import annotations

from pathlib import Path
from typing import List, Optional

from llama_index.core.schema import NodeWithScore

from src.core.config import Settings, get_settings
from src.core.logging_config import get_logger, setup_logging
from src.rag.hybrid_retriever import HybridSearchEngine
from src.rag.indexing import RAGIndexer

logger = get_logger(__name__)


class RAGPipeline:
    """
    RAG 端到端流水线。

    典型用法:
        pipeline = RAGPipeline()
        pipeline.build_index()                 # 从 document/ 全量构建
        result = pipeline.search("年假如何申请")  # 混合检索 + 重排序
    """

    def __init__(self, settings: Settings | None = None) -> None:
        setup_logging()
        self.settings = settings or get_settings()
        self.indexer = RAGIndexer(self.settings)
        self._search_engine: Optional[HybridSearchEngine] = None
        logger.info("RAGPipeline 初始化完成")

    def _ensure_search_engine(self) -> HybridSearchEngine:
        """懒加载检索引擎（依赖已有索引）。"""
        self.indexer.ensure_collection()
        if self._search_engine is None:
            vector_index = self.indexer.get_vector_index()
            storage_context = self.indexer.get_storage_context()
            self._search_engine = HybridSearchEngine(
                vector_index=vector_index,
                storage_context=storage_context,
                settings=self.settings,
                enable_rerank=self.settings.rag_enable_rerank,
            )
            logger.info("HybridSearchEngine 已就绪")
        return self._search_engine

    def invalidate_search_engine(self) -> None:
        """索引变更后使检索引擎失效，下次检索时重建。"""
        self._search_engine = None
        logger.info("检索引擎缓存已失效")

    def build_index(self, directory: Path | str | None = None, replace: bool = True) -> None:
        """
        从目录构建向量索引。

        参数:
            directory: 文档目录，默认使用配置中的 document/
            replace: 是否全量重建（True 会清空旧索引）
        """
        logger.info("开始构建 RAG 索引，replace=%s", replace)
        self.indexer.build_from_directory(directory=directory, replace=replace)
        self.invalidate_search_engine()
        logger.info("RAG 索引构建完成")

    def add_document(self, file_path: Path | str, document_id: Optional[str] = None) -> None:
        """增量将单个文档加入索引。"""
        logger.info("增量索引文档: %s，document_id=%s", file_path, document_id)
        try:
            self.indexer.add_file(file_path, document_id=document_id)
        except Exception as exc:  # noqa: BLE001
            msg = str(exc)
            if "does not exist" in msg or "NotFoundError" in type(exc).__name__:
                logger.warning("索引写入遇到失效 collection，刷新后重试: %s", exc)
                self.indexer.ensure_collection()
                self.invalidate_search_engine()
                self.indexer.add_file(file_path, document_id=document_id)
            else:
                raise
        self.invalidate_search_engine()
        logger.info("增量索引完成: %s", file_path)

    def delete_document(self, document_id: str) -> int:
        """按 document_id 从向量库/DocStore 移除，并刷新检索引擎。"""
        self.indexer.ensure_collection()
        removed = self.indexer.delete_by_document_id(document_id)
        self.invalidate_search_engine()
        return removed

    def search(self, query: str) -> dict:
        """
        执行混合检索 + 重排序，返回工具契约字典。

        返回示例:
            {"status": "success", "retrieved_nodes": [...]}
        """
        try:
            engine = self._ensure_search_engine()
            return engine.retrieve_as_dict(query)
        except Exception as exc:  # noqa: BLE001
            msg = str(exc)
            if "does not exist" in msg or "NotFoundError" in type(exc).__name__:
                logger.warning("检索遇到失效 collection，刷新后重试: %s", exc)
                self.indexer.ensure_collection()
                self.invalidate_search_engine()
                engine = self._ensure_search_engine()
                return engine.retrieve_as_dict(query)
            raise

    def search_nodes(self, query: str) -> List[NodeWithScore]:
        """执行检索并返回原始 NodeWithScore 列表（供内部调试）。"""
        engine = self._ensure_search_engine()
        return engine.retrieve(query)

    def format_context(self, query: str) -> str:
        """
        将检索结果格式化为可注入 Prompt 的上下文文本。

        若无结果，返回约定占位文案，供槽位 RETRIEVED_CONTEXT 使用。
        """
        result = self.search(query)
        nodes = result.get("retrieved_nodes") or []
        if not nodes:
            return "未检索到相关文档内容"

        blocks: List[str] = []
        for idx, item in enumerate(nodes, start=1):
            meta = item.get("metadata") or {}
            file_name = meta.get("file_name") or "unknown"
            score = item.get("score", 0.0)
            text = item.get("text", "")
            blocks.append(
                f"[片段 {idx}] 来源文件: {file_name} | 相关度: {score:.4f}\n{text}"
            )
        return "\n\n".join(blocks)


# 进程级单例，避免重复加载模型与 Chroma 连接
_pipeline_singleton: Optional[RAGPipeline] = None


def get_rag_pipeline() -> RAGPipeline:
    """获取全局 RAGPipeline 单例。"""
    global _pipeline_singleton
    if _pipeline_singleton is None:
        _pipeline_singleton = RAGPipeline()
    else:
        try:
            _pipeline_singleton.indexer.ensure_collection()
        except Exception as exc:  # noqa: BLE001
            logger.warning("RAG collection 自愈失败，将重建 Pipeline: %s", exc)
            _pipeline_singleton = RAGPipeline()
    return _pipeline_singleton


def reset_rag_pipeline() -> None:
    """丢弃单例（集合被清空/重建后调用）。"""
    global _pipeline_singleton
    _pipeline_singleton = None
    logger.info("RAGPipeline 单例已重置")
