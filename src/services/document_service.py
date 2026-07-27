# =============================================================================
# 文档上传与索引服务
# =============================================================================

from __future__ import annotations

import shutil
import uuid
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.config import get_settings
from src.core.database import AsyncSessionLocal
from src.core.logging_config import get_logger
from src.models.entities import DocumentRecord
from src.rag.pipeline import get_rag_pipeline
from src.services.document_converter import ensure_markdown_file

logger = get_logger(__name__)

ALLOWED_EXTENSIONS = {".md", ".markdown", ".doc", ".docx"}


async def save_upload_document(
    session: AsyncSession,
    *,
    filename: str,
    content: bytes,
    uploader_id: int | None,
) -> dict:
    """保存上传文件并写入 documents 表（status=indexing），立即返回。"""
    settings = get_settings()
    suffix = Path(filename).suffix.lower()
    if suffix not in ALLOWED_EXTENSIONS:
        raise ValueError("不支持的文件格式，仅允许 .md / .doc / .docx")

    document_id = f"doc_{uuid.uuid4().hex[:12]}"
    upload_dir = settings.upload_path
    upload_dir.mkdir(parents=True, exist_ok=True)

    raw_path = upload_dir / f"{document_id}_raw{suffix}"
    raw_path.write_bytes(content)
    file_size = len(content)

    record = DocumentRecord(
        document_id=document_id,
        file_name=filename,
        file_path=str(raw_path),
        file_size=file_size,
        file_type=suffix.lstrip("."),
        status="indexing",
        uploader_id=uploader_id,
    )
    session.add(record)
    await session.commit()

    logger.info(
        "文档已接收，等待后台索引 document_id=%s file=%s size=%d",
        document_id,
        filename,
        file_size,
    )
    return {
        "document_id": document_id,
        "file_name": filename,
        "file_size": file_size,
        "status": "indexing",
    }


async def index_document_background(document_id: str, filename: str) -> None:
    """后台执行 Word 转换与 RAG 索引，更新 status 为 ready / failed。"""
    import asyncio

    settings = get_settings()
    upload_dir = settings.upload_path
    suffix = Path(filename).suffix.lower()
    raw_path = upload_dir / f"{document_id}_raw{suffix}"

    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(DocumentRecord).where(DocumentRecord.document_id == document_id)
        )
        record = result.scalar_one_or_none()
        if record is None:
            logger.warning("后台索引跳过：记录不存在 document_id=%s", document_id)
            return

        if not raw_path.exists():
            record.status = "failed"
            await session.commit()
            logger.error("后台索引失败：原始文件不存在 %s", raw_path)
            return

        try:
            logger.info("后台索引开始 document_id=%s", document_id)

            def _convert_and_index() -> Path:
                md_path = ensure_markdown_file(
                    source_path=raw_path,
                    output_dir=upload_dir / "markdown",
                    document_id=document_id,
                )
                if md_path.suffix.lower() in {".md", ".markdown"} and md_path != raw_path:
                    archive = (
                        settings.document_path
                        / f"{document_id}_{Path(filename).stem}.md"
                    )
                    settings.document_path.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(md_path, archive)
                    index_target = archive
                else:
                    index_target = md_path
                pipeline = get_rag_pipeline()
                pipeline.add_document(index_target, document_id=document_id)
                return index_target

            # 必须放到线程池：同步 embedding/分片会阻塞事件循环，导致对话流式无响应
            index_target = await asyncio.to_thread(_convert_and_index)

            record.status = "ready"
            record.file_path = str(index_target)
            await session.commit()
            logger.info("后台索引完成 document_id=%s", document_id)
        except Exception as exc:  # noqa: BLE001
            record.status = "failed"
            await session.commit()
            logger.exception("后台索引失败 document_id=%s: %s", document_id, exc)


async def list_documents(session: AsyncSession) -> list[dict]:
    """查询文档列表。"""
    result = await session.execute(
        select(DocumentRecord).order_by(DocumentRecord.created_at.desc())
    )
    rows = result.scalars().all()
    items = []
    for row in rows:
        upload_time = row.created_at.isoformat() if row.created_at else None
        items.append(
            {
                "document_id": row.document_id,
                "file_name": row.file_name,
                "upload_time": upload_time,
                "status": row.status,
            }
        )
    return items


def _safe_unlink(path: Path) -> None:
    try:
        if path.is_file():
            path.unlink()
            logger.info("已删除文件: %s", path)
    except OSError as exc:
        logger.warning("删除文件失败 %s: %s", path, exc)


async def delete_document(session: AsyncSession, document_id: str) -> dict:
    """删除文档记录：数据库行 + 本地文件 + RAG 索引节点。"""
    result = await session.execute(
        select(DocumentRecord).where(DocumentRecord.document_id == document_id)
    )
    record = result.scalar_one_or_none()
    if record is None:
        raise LookupError(f"文档不存在: {document_id}")

    settings = get_settings()
    upload_dir = settings.upload_path

    removed_nodes = 0
    try:
        pipeline = get_rag_pipeline()
        removed_nodes = pipeline.delete_document(document_id)
    except Exception as exc:  # noqa: BLE001
        logger.warning("删除索引时忽略异常 document_id=%s: %s", document_id, exc)

    known_paths = [
        Path(record.file_path) if record.file_path else None,
        upload_dir / "markdown" / f"{document_id}.md",
    ]
    for p in known_paths:
        if p is not None:
            _safe_unlink(p)

    for raw in upload_dir.glob(f"{document_id}_raw*"):
        _safe_unlink(raw)

    if settings.document_path.exists():
        for archived in settings.document_path.glob(f"{document_id}_*"):
            _safe_unlink(archived)

    await session.delete(record)
    await session.commit()
    logger.info(
        "文档已删除 document_id=%s file_name=%s removed_nodes=%d",
        document_id,
        record.file_name,
        removed_nodes,
    )
    return {
        "document_id": document_id,
        "file_name": record.file_name,
        "removed_nodes": removed_nodes,
    }

