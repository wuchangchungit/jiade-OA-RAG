# 清理 Chroma 脏数据，并按数据库中 ready/failed 可恢复文档重建索引
from __future__ import annotations

import asyncio
from pathlib import Path

from sqlalchemy import select

from src.core.database import AsyncSessionLocal
from src.core.logging_config import get_logger, setup_logging
from src.models.entities import DocumentRecord
from src.rag.pipeline import get_rag_pipeline, reset_rag_pipeline

logger = get_logger(__name__)


async def main() -> None:
    setup_logging()
    reset_rag_pipeline()
    pipeline = get_rag_pipeline()
    logger.info("清空 Chroma / DocStore ...")
    pipeline.indexer._reset_storage()  # noqa: SLF001
    pipeline.invalidate_search_engine()

    async with AsyncSessionLocal() as session:
        result = await session.execute(select(DocumentRecord))
        rows = list(result.scalars().all())

        ready_or_retry = []
        for row in rows:
            path = Path(row.file_path) if row.file_path else None
            if path is None or not path.exists():
                # 尝试原始上传文件
                upload = Path("/app/data/uploads")
                candidates = list(upload.glob(f"{row.document_id}_raw*"))
                if candidates:
                    path = candidates[0]
                else:
                    logger.warning(
                        "文件不存在，保持原状态 %s %s", row.document_id, row.file_name
                    )
                    continue
            ready_or_retry.append((row, path))

        logger.info("待重建文档数=%d", len(ready_or_retry))
        for row, path in ready_or_retry:
            try:
                logger.info("重建索引 %s -> %s", row.document_id, path)
                pipeline.add_document(path, document_id=row.document_id)
                row.status = "ready"
                row.file_path = str(path)
                await session.commit()
                logger.info("重建成功 %s", row.document_id)
            except Exception as exc:  # noqa: BLE001
                row.status = "failed"
                await session.commit()
                logger.exception("重建失败 %s: %s", row.document_id, exc)

    logger.info(
        "清理完成，Chroma 文档数=%d",
        pipeline.indexer._chroma_collection.count(),  # noqa: SLF001
    )


if __name__ == "__main__":
    asyncio.run(main())
