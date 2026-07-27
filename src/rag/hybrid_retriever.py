# =============================================================================
# 混合检索模块
# 向量检索 + BM25 关键词检索，经 RRF 融合后交给 AutoMergingRetriever / 重排序
# =============================================================================

from __future__ import annotations

from collections import defaultdict
from typing import Dict, List, Optional, Sequence

from llama_index.core import StorageContext, VectorStoreIndex
from llama_index.core.retrievers import AutoMergingRetriever, BaseRetriever
from llama_index.core.schema import NodeRelationship, NodeWithScore, QueryBundle

from src.core.config import Settings, get_settings
from src.core.logging_config import get_logger
from src.rag.reranker import RerankService

logger = get_logger(__name__)


def reciprocal_rank_fusion(
    result_lists: Sequence[Sequence[NodeWithScore]],
    k: int = 60,
) -> List[NodeWithScore]:
    """
    Reciprocal Rank Fusion (RRF) 融合多路检索结果。

    公式: score(d) = sum(1 / (k + rank_i(d)))
    """
    fused_scores: Dict[str, float] = defaultdict(float)
    node_map: Dict[str, NodeWithScore] = {}

    for result_list in result_lists:
        for rank, item in enumerate(result_list, start=1):
            node_id = item.node.node_id
            fused_scores[node_id] += 1.0 / (k + rank)
            if node_id not in node_map:
                node_map[node_id] = item

    ranked_ids = sorted(fused_scores.keys(), key=lambda nid: fused_scores[nid], reverse=True)
    fused: List[NodeWithScore] = []
    for nid in ranked_ids:
        original = node_map[nid]
        fused.append(NodeWithScore(node=original.node, score=fused_scores[nid]))
    return fused


class HybridAutoMergingRetriever(BaseRetriever):
    """
    高级检索器：混合检索（向量 + BM25） + AutoMerging + 可选重排序。

    流程:
      1. 向量相似度召回 Top-K
      2. BM25 关键词召回 Top-K
      3. RRF 融合去重
      4. AutoMergingRetriever 将足够多的子块合并回父块
      5. RerankService 重排序并截断 Top-N
    """

    def __init__(
        self,
        vector_index: VectorStoreIndex,
        storage_context: StorageContext,
        settings: Settings | None = None,
        reranker: RerankService | None = None,
        enable_rerank: bool = True,
    ) -> None:
        super().__init__()
        self.settings = settings or get_settings()
        self.vector_index = vector_index
        self.storage_context = storage_context
        self.top_k = self.settings.rag_retrieve_top_k
        self.enable_rerank = enable_rerank
        self.reranker = reranker or RerankService(self.settings)

        self._vector_retriever = vector_index.as_retriever(similarity_top_k=self.top_k)
        self._auto_merging_retriever = AutoMergingRetriever(
            self._vector_retriever,
            storage_context=storage_context,
            verbose=False,
        )
        self._bm25_retriever = self._build_bm25_retriever()

        logger.info(
            "HybridAutoMergingRetriever 初始化完成，top_k=%d，enable_rerank=%s",
            self.top_k,
            self.enable_rerank,
        )

    def _build_bm25_retriever(self):
        """构建 BM25 检索器；依赖 llama-index-retrievers-bm25。"""
        try:
            from llama_index.retrievers.bm25 import BM25Retriever
        except ImportError as exc:
            logger.error(
                "未安装 llama-index-retrievers-bm25，BM25 检索不可用: %s",
                exc,
            )
            return None

        nodes = list(self.storage_context.docstore.docs.values())
        if not nodes:
            logger.warning("DocStore 为空，无法构建 BM25 检索器")
            return None

        # 仅对叶子节点做 BM25，与向量库粒度对齐
        leaf_like = []
        for n in nodes:
            child_rel = n.relationships.get(NodeRelationship.CHILD)
            if child_rel is None:
                leaf_like.append(n)
        corpus = leaf_like if leaf_like else nodes
        logger.info("构建 BM25 检索器，语料节点数=%d", len(corpus))
        return BM25Retriever.from_defaults(nodes=corpus, similarity_top_k=self.top_k)

    def _retrieve(self, query_bundle: QueryBundle) -> List[NodeWithScore]:
        """实现 BaseRetriever 接口的核心检索逻辑。"""
        query = query_bundle.query_str
        logger.info("混合检索开始，query=%s", query[:120])

        # ----- 1) 向量 + AutoMerging -----
        try:
            vector_nodes = self._auto_merging_retriever.retrieve(query_bundle)
            logger.info("向量/AutoMerging 召回数量=%d", len(vector_nodes))
        except Exception as exc:  # noqa: BLE001
            logger.exception("向量检索失败，尝试降级为纯向量: %s", exc)
            vector_nodes = self._vector_retriever.retrieve(query_bundle)

        # ----- 2) BM25 -----
        bm25_nodes: List[NodeWithScore] = []
        if self._bm25_retriever is not None:
            try:
                bm25_nodes = self._bm25_retriever.retrieve(query_bundle)
                logger.info("BM25 召回数量=%d", len(bm25_nodes))
            except Exception as exc:  # noqa: BLE001
                logger.exception("BM25 检索失败，将仅使用向量结果: %s", exc)

        # ----- 3) RRF 融合 -----
        if bm25_nodes:
            fused = reciprocal_rank_fusion([vector_nodes, bm25_nodes])
            logger.info("RRF 融合后候选数=%d", len(fused))
        else:
            fused = list(vector_nodes)
            logger.info("无 BM25 结果，直接使用向量召回，数量=%d", len(fused))

        fused = fused[: self.top_k]

        # ----- 4) 重排序 -----
        if self.enable_rerank and fused:
            return self.reranker.rerank(query=query, nodes=fused)

        return fused[: self.settings.rag_rerank_top_n]


class HybridSearchEngine:
    """
    混合检索引擎门面。

    封装 HybridAutoMergingRetriever，对外提供简单的 retrieve(query) API，
    并格式化输出为工具契约所需的结构。
    """

    def __init__(
        self,
        vector_index: VectorStoreIndex,
        storage_context: StorageContext,
        settings: Settings | None = None,
        enable_rerank: bool = True,
    ) -> None:
        self.settings = settings or get_settings()
        self.retriever = HybridAutoMergingRetriever(
            vector_index=vector_index,
            storage_context=storage_context,
            settings=self.settings,
            enable_rerank=enable_rerank,
        )

    def retrieve(self, query: str) -> List[NodeWithScore]:
        """执行混合检索 + 重排序，返回 NodeWithScore 列表。"""
        if not query or not query.strip():
            logger.warning("检索 query 为空")
            return []
        return self.retriever.retrieve(query)

    def retrieve_as_dict(self, query: str) -> dict:
        """
        按 ems_handbook_tool 输出契约返回字典。

        结构:
          {
            "status": "success",
            "retrieved_nodes": [
              {"text": "...", "score": 0.9, "metadata": {...}},
              ...
            ]
          }
        """
        try:
            nodes = self.retrieve(query)
            retrieved = []
            for item in nodes:
                meta = dict(item.node.metadata or {})
                retrieved.append(
                    {
                        "text": item.node.get_content(),
                        "score": float(item.score) if item.score is not None else 0.0,
                        "metadata": {
                            "file_name": meta.get("file_name", ""),
                            "document_id": meta.get("document_id", ""),
                            "chunk_id": meta.get("chunk_id", ""),
                            "node_id": meta.get("node_id", item.node.node_id),
                            "page_number": meta.get("page_number", meta.get("page_label")),
                        },
                    }
                )
            result = {"status": "success", "retrieved_nodes": retrieved}
            logger.info("检索成功，返回节点数=%d", len(retrieved))
            return result
        except Exception as exc:  # noqa: BLE001
            logger.exception("混合检索失败: %s", exc)
            return {
                "status": "error",
                "error_code": "2002",
                "message": str(exc),
                "retrieved_nodes": [],
            }