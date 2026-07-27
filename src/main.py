# =============================================================================
# FastAPI 应用入口
# 启动方式（conda test 环境）:
#   conda activate test
#   uvicorn src.main:app --host 0.0.0.0 --port 8000 --reload
# =============================================================================

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from src.api.router import api_router
from src.core.config import PROJECT_ROOT, get_settings
from src.core.database import AsyncSessionLocal, init_db
from src.core.logging_config import get_logger, setup_logging
from src.core.response import fail
from src.services.auth_service import ensure_demo_user

logger = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期：启动时初始化日志、数据库、演示账号，并预热 RAG。"""
    setup_logging()
    settings = get_settings()
    settings.upload_path.mkdir(parents=True, exist_ok=True)
    settings.document_path.mkdir(parents=True, exist_ok=True)
    settings.chroma_path.mkdir(parents=True, exist_ok=True)

    try:
        await init_db()
        async with AsyncSessionLocal() as session:
            await ensure_demo_user(session)
        logger.info("应用启动完成，env=%s", settings.app_env)
    except Exception as exc:  # noqa: BLE001
        logger.exception("启动初始化失败（请检查 Postgres 是否已 docker compose up）: %s", exc)

    async def _warmup_rag() -> None:
        try:
            from src.rag.pipeline import get_rag_pipeline

            await asyncio.to_thread(get_rag_pipeline)
            logger.info("RAG 流水线预热完成")
        except Exception as exc:  # noqa: BLE001
            logger.warning("RAG 流水线预热失败（不影响启动）: %s", exc)

    asyncio.create_task(_warmup_rag())

    yield
    logger.info("应用正在关闭")


app = FastAPI(
    title="RAG Agent 多轮对话系统",
    description="上海佳得森辉新材料(集团)有限公司 RAG 问答 Demo（作者：吴常春）",
    version="0.4.0",
    lifespan=lifespan,
)

# 前后端分离：开发期允许本地前端跨域
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(api_router)

# 静态资源与模板（登录页 / 主工作区）
static_dir = PROJECT_ROOT / "static"
templates_dir = PROJECT_ROOT / "templates"
static_dir.mkdir(parents=True, exist_ok=True)
templates_dir.mkdir(parents=True, exist_ok=True)
app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")
templates = Jinja2Templates(directory=str(templates_dir))


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    """参数校验失败统一返回。"""
    logger.warning("请求参数校验失败 path=%s errors=%s", request.url.path, exc.errors())
    return JSONResponse(status_code=400, content=fail(message="请求参数错误", code=400))


@app.get("/health")
async def health():
    """健康检查。"""
    return {"status": "ok"}


@app.get("/login")
async def login_page(request: Request):
    """登录页。"""
    return templates.TemplateResponse("login.html", {"request": request})


@app.get("/")
async def index(request: Request):
    """
    主工作区页面。
    前端 JS 会在无 Token 时自动跳转到 /login。
    """
    return templates.TemplateResponse("index.html", {"request": request})


if __name__ == "__main__":
    import uvicorn

    settings = get_settings()
    uvicorn.run(
        "src.main:app",
        host=settings.app_host,
        port=settings.app_port,
        reload=True,
    )