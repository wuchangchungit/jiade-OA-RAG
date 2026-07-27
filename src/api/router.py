# =============================================================================
# API router
# =============================================================================

from __future__ import annotations

from fastapi import APIRouter

from src.api import auth, chat, documents

api_router = APIRouter(prefix="/api/v1")
api_router.include_router(auth.router)
api_router.include_router(documents.router)
api_router.include_router(chat.router)
