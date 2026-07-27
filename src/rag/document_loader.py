# =============================================================================
# 文档加载模块
# 使用 LlamaIndex 从指定目录加载 Markdown / Word 文档
# =============================================================================

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, List, Optional, Sequence

from llama_index.core import Document, SimpleDirectoryReader

from src.core.logging_config import get_logger

logger = get_logger(__name__)

# 支持的文档后缀
SUPPORTED_SUFFIXES: tuple[str, ...] = (".md", ".markdown", ".txt", ".docx", ".doc")


def _build_base_metadata(file_path: Path, document_id: Optional[str] = None) -> dict:
    """为单个文件构造统一的元数据字段。"""
    doc_id = document_id or f"doc_{uuid.uuid4().hex[:12]}"
    return {
        "document_id": doc_id,
        "file_name": file_path.name,
        "file_path": str(file_path.resolve()),
        "file_type": file_path.suffix.lstrip(".").lower(),
        "created_at": datetime.now(timezone.utc).isoformat(),
    }


def load_documents_from_dir(
    directory: Path | str,
    recursive: bool = True,
    allowed_suffixes: Sequence[str] = SUPPORTED_SUFFIXES,
) -> List[Document]:
    """
    从目录加载文档，返回 LlamaIndex Document 列表。

    参数:
        directory: 文档目录
        recursive: 是否递归子目录
        allowed_suffixes: 允许的文件后缀
    """
    dir_path = Path(directory)
    if not dir_path.exists():
        logger.warning("文档目录不存在: %s", dir_path)
        return []

    if recursive:
        pattern_iter: Iterable[Path] = dir_path.rglob("*")
    else:
        pattern_iter = dir_path.glob("*")

    target_files = [
        p
        for p in pattern_iter
        if p.is_file() and p.suffix.lower() in {s.lower() for s in allowed_suffixes}
    ]

    if not target_files:
        logger.warning("目录中未找到可加载文档: %s", dir_path)
        return []

    logger.info("开始加载文档，目录=%s，文件数=%d", dir_path, len(target_files))

    reader = SimpleDirectoryReader(
        input_files=[str(p) for p in target_files],
        filename_as_id=True,
    )
    documents = reader.load_data()

    file_map = {str(p.resolve()): p for p in target_files}
    for doc in documents:
        raw_path = doc.metadata.get("file_path") or doc.metadata.get("file_name")
        resolved: Optional[Path] = None
        if raw_path:
            candidate = Path(raw_path)
            if not candidate.is_absolute():
                for fp in target_files:
                    if fp.name == candidate.name:
                        resolved = fp
                        break
            else:
                resolved = file_map.get(str(candidate.resolve()), candidate)

        if resolved is None and target_files:
            for fp in target_files:
                if fp.name in str(doc.doc_id):
                    resolved = fp
                    break

        if resolved is not None:
            base_meta = _build_base_metadata(resolved)
            doc.metadata.update(base_meta)
            if not doc.doc_id or doc.doc_id.startswith("doc_"):
                doc.doc_id = base_meta["document_id"]

    logger.info("文档加载完成，共 %d 个 Document", len(documents))
    return documents


def load_single_document(
    file_path: Path | str,
    document_id: Optional[str] = None,
) -> List[Document]:
    """
    加载单个文件为 Document 列表。

    参数:
        file_path: 文件路径
        document_id: 可选的业务文档 ID，便于与数据库 documents 表关联
    """
    path = Path(file_path)
    if not path.exists() or not path.is_file():
        raise FileNotFoundError(f"文件不存在: {path}")

    suffix = path.suffix.lower()
    if suffix not in SUPPORTED_SUFFIXES:
        raise ValueError(
            f"不支持的文件格式: {suffix}，仅支持 {SUPPORTED_SUFFIXES}"
        )

    logger.info("加载单个文档: %s", path)
    reader = SimpleDirectoryReader(input_files=[str(path)], filename_as_id=True)
    documents = reader.load_data()
    base_meta = _build_base_metadata(path, document_id=document_id)
    for doc in documents:
        doc.metadata.update(base_meta)
        doc.doc_id = base_meta["document_id"]
    return documents