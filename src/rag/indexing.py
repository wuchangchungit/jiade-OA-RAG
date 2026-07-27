# =============================================================================
# 索引构建模块
# 父子块分片（HierarchicalNodeParser）+ Chroma 向量持久化
# =============================================================================

from __future__ import annotations

import json
from pathlib import Path
from typing import List, Optional, Sequence

import chromadb
from llama_index.core import Document, StorageContext, VectorStoreIndex
from llama_index.core.node_parser import (
    HierarchicalNodeParser,
    get_leaf_nodes,
)
from llama_index.core.schema import BaseNode
from llama_index.core.storage.docstore import SimpleDocumentStore
from llama_index.vector_stores.chroma import ChromaVectorStore

from src.core.config import Settings, get_settings
from src.core.logging_config import get_logger
from src.rag.document_loader import load_documents_from_dir, load_single_document
from src.rag.embeddings import build_embed_model

logger = get_logger(__name__)

# DocStore 旁路文件名：保存全部父子节点，供 AutoMergingRetriever 使用
DOCSTORE_FILENAME = "docstore.json"
# 记录索引元信息，便于排查
INDEX_META_FILENAME = "index_meta.json"


class RAGIndexer:
    """
    RAG 索引构建器。

    核心流程：
      1. 加载 Document
      2. HierarchicalNodeParser 生成父子层级节点
      3. 仅将叶子节点（子块）写入 Chroma
      4. 全部节点（含父块）写入本地 DocStore，供 AutoMerging 合并
    """

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        self.persist_dir: Path = self.settings.chroma_path
        self.collection_name: str = self.settings.chroma_collection_name
        self.persist_dir.mkdir(parents=True, exist_ok=True)

        self._embed_model = build_embed_model(self.settings)
        self._chroma_client = chromadb.PersistentClient(path=str(self.persist_dir))
        self._chroma_collection = self._chroma_client.get_or_create_collection(
            name=self.collection_name
        )
        self._vector_store = ChromaVectorStore(chroma_collection=self._chroma_collection)
        self._docstore = self._load_or_create_docstore()

        logger.info(
            "RAGIndexer 初始化完成，persist_dir=%s，collection=%s",
            self.persist_dir,
            self.collection_name,
        )

    def _bind_collection(self) -> None:
        """重新绑定 Chroma collection 与 VectorStore（集合被外部重建后必需）。"""
        self._chroma_collection = self._chroma_client.get_or_create_collection(
            name=self.collection_name
        )
        self._vector_store = ChromaVectorStore(chroma_collection=self._chroma_collection)
        logger.info("已重新绑定 Chroma collection: %s", self.collection_name)

    def ensure_collection(self) -> None:
        """若当前 collection 句柄失效（被删除），自动恢复。"""
        try:
            _ = self._chroma_collection.count()
        except Exception as exc:  # noqa: BLE001
            logger.warning("Chroma collection 不可用，尝试恢复: %s", exc)
            self._bind_collection()

    def _docstore_path(self) -> Path:
        return self.persist_dir / DOCSTORE_FILENAME

    def _load_or_create_docstore(self) -> SimpleDocumentStore:
        """加载已有 DocStore；不存在则新建空库。"""
        path = self._docstore_path()
        if path.exists():
            try:
                docstore = SimpleDocumentStore.from_persist_path(str(path))
                logger.info("已加载 DocStore: %s，节点数≈%d", path, len(docstore.docs))
                return docstore
            except Exception as exc:  # noqa: BLE001
                logger.exception("加载 DocStore 失败，将重建空库: %s", exc)
        return SimpleDocumentStore()

    def _persist_docstore(self) -> None:
        """将 DocStore 持久化到磁盘。"""
        path = self._docstore_path()
        self._docstore.persist(persist_path=str(path))
        logger.info("DocStore 已持久化: %s，节点数=%d", path, len(self._docstore.docs))

    def _write_index_meta(self, extra: Optional[dict] = None) -> None:
        """写入索引元信息，便于运维排查。"""
        meta = {
            "collection_name": self.collection_name,
            "parent_chunk_size": self.settings.rag_parent_chunk_size,
            "child_chunk_size": self.settings.rag_child_chunk_size,
            "embedding_provider": self.settings.embedding_provider,
            "node_count": len(self._docstore.docs),
            "chroma_count": self._chroma_collection.count(),
        }
        if extra:
            meta.update(extra)
        meta_path = self.persist_dir / INDEX_META_FILENAME
        meta_path.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")

    def parse_hierarchical_nodes(
        self,
        documents: Sequence[Document],
    ) -> List[BaseNode]:
        """
        使用 HierarchicalNodeParser 进行父子块分片。

        - 父块大小: rag_parent_chunk_size
        - 子块大小: rag_child_chunk_size
        - 返回全部节点（父 + 子），后续仅叶子入向量库
        """
        chunk_sizes = [
            self.settings.rag_parent_chunk_size,
            self.settings.rag_child_chunk_size,
        ]
        logger.info(
            "开始父子分片，文档数=%d，chunk_sizes=%s",
            len(documents),
            chunk_sizes,
        )
        parser = HierarchicalNodeParser.from_defaults(chunk_sizes=chunk_sizes)
        nodes = parser.get_nodes_from_documents(list(documents), show_progress=True)

        for idx, node in enumerate(nodes):
            node.metadata.setdefault("chunk_id", f"chunk_{idx:05d}")
            node.metadata.setdefault("node_id", node.node_id)

        leaf_count = len(get_leaf_nodes(nodes))
        logger.info(
            "分片完成，总节点=%d，叶子节点(子块)=%d，父块≈%d",
            len(nodes),
            leaf_count,
            len(nodes) - leaf_count,
        )
        return nodes

    def index_nodes(self, nodes: Sequence[BaseNode], replace: bool = False) -> VectorStoreIndex:
        """
        将节点写入 DocStore + Chroma。

        参数:
            nodes: HierarchicalNodeParser 产出的全部节点
            replace: True 时清空集合后重建（全量重建场景）
        """
        if replace:
            logger.warning("replace=True，将清空 Chroma 集合与 DocStore 后重建")
            self._reset_storage()

        self.ensure_collection()
        self._docstore.add_documents(list(nodes))

        leaf_nodes = get_leaf_nodes(list(nodes))
        if not leaf_nodes:
            logger.warning("没有叶子节点可写入向量库")
            self._persist_docstore()
            return self.get_vector_index()

        storage_context = StorageContext.from_defaults(
            vector_store=self._vector_store,
            docstore=self._docstore,
        )

        logger.info("开始向 Chroma 写入叶子节点，数量=%d", len(leaf_nodes))
        index = VectorStoreIndex(
            nodes=leaf_nodes,
            storage_context=storage_context,
            embed_model=self._embed_model,
            show_progress=True,
        )
        self._persist_docstore()
        self._write_index_meta({"last_action": "index_nodes", "leaf_written": len(leaf_nodes)})
        logger.info(
            "索引写入完成，Chroma 文档数=%d",
            self._chroma_collection.count(),
        )
        return index

    def _reset_storage(self) -> None:
        """清空 Chroma 集合与 DocStore。"""
        try:
            self._chroma_client.delete_collection(self.collection_name)
        except Exception as exc:  # noqa: BLE001
            logger.warning("删除 Chroma 集合时忽略异常: %s", exc)
        self._bind_collection()
        self._docstore = SimpleDocumentStore()
        docstore_path = self._docstore_path()
        if docstore_path.exists():
            docstore_path.unlink()

    def build_from_directory(
        self,
        directory: Path | str | None = None,
        replace: bool = True,
    ) -> VectorStoreIndex:
        """从目录加载文档并全量/增量构建索引。"""
        dir_path = Path(directory) if directory else self.settings.document_path
        documents = load_documents_from_dir(dir_path)
        if not documents:
            raise FileNotFoundError(f"目录无可用文档，无法构建索引: {dir_path}")
        nodes = self.parse_hierarchical_nodes(documents)
        return self.index_nodes(nodes, replace=replace)

    def add_file(
        self,
        file_path: Path | str,
        document_id: Optional[str] = None,
    ) -> VectorStoreIndex:
        """增量添加单个文件到索引（不清空已有数据）。"""
        documents = load_single_document(file_path, document_id=document_id)
        nodes = self.parse_hierarchical_nodes(documents)
        return self.index_nodes(nodes, replace=False)

    def delete_by_document_id(self, document_id: str) -> int:
        """
        按业务 document_id 从 DocStore 与 Chroma 删除相关节点。

        返回删除的 DocStore 节点数（失败文档可能为 0）。
        """
        if not document_id:
            return 0

        self.ensure_collection()

        node_ids: list[str] = []
        for nid, node in list(self._docstore.docs.items()):
            meta = getattr(node, "metadata", None) or {}
            if meta.get("document_id") == document_id:
                node_ids.append(nid)

        for nid in node_ids:
            try:
                self._docstore.delete_document(nid)
            except Exception as exc:  # noqa: BLE001
                logger.warning("DocStore 删除节点失败 id=%s: %s", nid, exc)

        # Chroma：按 metadata 过滤删除（失败索引时可能无向量）
        try:
            self._chroma_collection.delete(where={"document_id": document_id})
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "Chroma 按 document_id 删除失败，尝试按 node id 删除: %s", exc
            )
            if node_ids:
                try:
                    self._chroma_collection.delete(ids=node_ids)
                except Exception as exc2:  # noqa: BLE001
                    logger.warning("Chroma 按 ids 删除失败: %s", exc2)

        if node_ids:
            self._persist_docstore()
            self._write_index_meta(
                {
                    "last_action": "delete_by_document_id",
                    "document_id": document_id,
                    "nodes_removed": len(node_ids),
                }
            )

        logger.info(
            "已从索引移除 document_id=%s，DocStore 节点数=%d",
            document_id,
            len(node_ids),
        )
        return len(node_ids)

    def get_vector_index(self) -> VectorStoreIndex:
        """基于已有 Chroma + DocStore 还原 VectorStoreIndex（不重新 embedding）。"""
        self.ensure_collection()
        storage_context = StorageContext.from_defaults(
            vector_store=self._vector_store,
            docstore=self._docstore,
        )
        return VectorStoreIndex.from_vector_store(
            vector_store=self._vector_store,
            storage_context=storage_context,
            embed_model=self._embed_model,
        )

    def get_storage_context(self) -> StorageContext:
        """返回包含 DocStore 与 VectorStore 的 StorageContext。"""
        self.ensure_collection()
        return StorageContext.from_defaults(
            vector_store=self._vector_store,
            docstore=self._docstore,
        )

    @property
    def docstore(self) -> SimpleDocumentStore:
        """暴露 DocStore，供检索器使用。"""
        return self._docstore

    @property
    def vector_store(self) -> ChromaVectorStore:
        """暴露 ChromaVectorStore。"""
        return self._vector_store