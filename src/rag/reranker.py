# =============================================================================
# 重排序模块
# 对混合检索候选结果使用 CrossEncoder / SentenceTransformer 重排序
# =============================================================================

from __future__ import annotations

from typing import List, Optional, Sequence

from llama_index.core.postprocessor import SentenceTransformerRerank
from llama_index.core.schema import NodeWithScore, QueryBundle

from src.core.config import Settings, get_settings
from src.core.logging_config import get_logger

logger = get_logger(__name__)


class RerankService:
    """
    重排序服务。

    默认使用 SentenceTransformerRerank（CrossEncoder），
    对召回的候选节点按与 query 的相关性重新打分并截断 Top-N。
    """

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        self.top_n = self.settings.rag_rerank_top_n
        self.model_name = self.settings.rerank_model_name
        self._postprocessor: Optional[SentenceTransformerRerank] = None
        self._load_failed: bool = False
        logger.info(
            "RerankService 配置完成，model=%s，top_n=%d",
            self.model_name,
            self.top_n,
        )

    def _get_postprocessor(self) -> SentenceTransformerRerank:
        """延迟加载重排序模型，避免导入阶段即下载权重。"""
        if self._load_failed:
            raise RuntimeError(
                f"重排序模型此前加载失败，已跳过: {self.model_name}"
            )
        if self._postprocessor is None:
            logger.info("正在加载重排序模型: %s", self.model_name)
            self._postprocessor = SentenceTransformerRerank(
                model=self.model_name,
                top_n=self.top_n,
            )
            logger.info("重排序模型加载完成")
        return self._postprocessor

    def rerank(
        self,
        query: str,
        nodes: Sequence[NodeWithScore],
        top_n: Optional[int] = None,
    ) -> List[NodeWithScore]:
        """
        对候选节点重排序。

        参数:
            query: 用户查询
            nodes: 混合检索召回的候选
            top_n: 覆盖默认返回数量；为空则用配置值
        """
        if not nodes:
            logger.warning("重排序输入节点为空，直接返回")
            return []

        effective_top_n = top_n if top_n is not None else self.top_n

        try:
            postprocessor = self._get_postprocessor()
        except Exception as exc:  # noqa: BLE001
            self._load_failed = True
            logger.exception(
                "重排序模型加载失败，降级为按原分数截断: %s", exc
            )
            sorted_nodes = sorted(
                nodes,
                key=lambda n: n.score if n.score is not None else 0.0,
                reverse=True,
            )
            return list(sorted_nodes[:effective_top_n])

        original_top_n = postprocessor.top_n
        postprocessor.top_n = effective_top_n

        try:
            logger.info(
                "开始重排序，候选数=%d，top_n=%d，query=%s",
                len(nodes),
                effective_top_n,
                query[:80],
            )
            query_bundle = QueryBundle(query_str=query)
            reranked = postprocessor.postprocess_nodes(
                list(nodes),
                query_bundle=query_bundle,
            )
            logger.info("重排序完成，输出节点数=%d", len(reranked))
            return reranked
        except Exception as exc:  # noqa: BLE001
            logger.exception("重排序失败，降级为按原分数截断: %s", exc)
            sorted_nodes = sorted(
                nodes,
                key=lambda n: n.score if n.score is not None else 0.0,
                reverse=True,
            )
            return list(sorted_nodes[:effective_top_n])
        finally:
            postprocessor.top_n = original_top_n