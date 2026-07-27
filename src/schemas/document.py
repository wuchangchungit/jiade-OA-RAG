# =============================================================================
# 文档管理 Schema
# =============================================================================

from __future__ import annotations

from typing import List, Optional

from pydantic import BaseModel


class DocumentUploadData(BaseModel):
    """上传文档响应。"""

    document_id: str
    file_name: str
    file_size: int
    status: str


class DocumentItem(BaseModel):
    """文档列表项。"""

    document_id: str
    file_name: str
    upload_time: Optional[str] = None
    status: str


class DocumentListData(BaseModel):
    """文档列表响应。"""

    documents: List[DocumentItem]