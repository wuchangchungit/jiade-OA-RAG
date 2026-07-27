# =============================================================================
# 文档管理接口：上传 / 列表 / 删除
# =============================================================================

from __future__ import annotations

import asyncio

from fastapi import APIRouter, Depends, File, UploadFile
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.deps import get_current_user
from src.core.database import get_db_session
from src.core.logging_config import get_logger
from src.core.response import fail, ok
from src.models.entities import User
from src.services.document_service import (
    delete_document,
    index_document_background,
    list_documents,
    save_upload_document,
)

logger = get_logger(__name__)
router = APIRouter(prefix="/documents", tags=["documents"])


def _schedule_background_index(document_id: str, filename: str) -> None:
    """真正的 fire-and-forget，避免拖住上传 HTTP 响应。"""
    task = asyncio.create_task(index_document_background(document_id, filename))

    def _on_done(t: asyncio.Task) -> None:
        try:
            t.result()
        except Exception as exc:  # noqa: BLE001
            logger.exception(
                "后台索引任务异常 document_id=%s: %s", document_id, exc
            )

    task.add_done_callback(_on_done)


@router.post("/upload")
async def upload_document(
    file: UploadFile = File(...),
    session: AsyncSession = Depends(get_db_session),
    current_user: User = Depends(get_current_user),
):
    """上传文件后立即返回；转换与向量化在后台异步执行。"""
    filename = file.filename or "unknown"
    content = await file.read()
    if not content:
        return fail(message="上传文件为空", code=400)
    try:
        data = await save_upload_document(
            session,
            filename=filename,
            content=content,
            uploader_id=current_user.id,
        )
        _schedule_background_index(data["document_id"], filename)
        return ok(data=data, message="文件已接收，正在后台建立索引")
    except ValueError as exc:
        logger.warning("文档上传参数错误: %s", exc)
        return fail(message=str(exc), code=400)
    except Exception as exc:  # noqa: BLE001
        logger.exception("文档上传失败: %s", exc)
        return fail(message=f"文档上传失败: {exc}", code=500)


@router.get("/list")
async def get_document_list(
    session: AsyncSession = Depends(get_db_session),
    current_user: User = Depends(get_current_user),
):
    """获取已加载文档列表。"""
    _ = current_user
    docs = await list_documents(session)
    return ok(data={"documents": docs}, message="操作成功")


@router.delete("/{document_id}")
async def remove_document(
    document_id: str,
    session: AsyncSession = Depends(get_db_session),
    current_user: User = Depends(get_current_user),
):
    """删除文档记录及其索引/本地文件（ready / failed / indexing 均可）。"""
    _ = current_user
    try:
        data = await delete_document(session, document_id)
        return ok(data=data, message="文档已删除")
    except LookupError as exc:
        return fail(message=str(exc), code=404)
    except Exception as exc:  # noqa: BLE001
        logger.exception("删除文档失败 document_id=%s: %s", document_id, exc)
        return fail(message=f"删除文档失败: {exc}", code=500)
