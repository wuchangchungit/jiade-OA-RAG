# =============================================================================
# 日志配置模块
# 统一初始化控制台 + 滚动文件日志，方便后台排查
# =============================================================================

from __future__ import annotations

import logging
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path

from src.core.config import get_settings

# 标记是否已完成初始化，避免重复添加 Handler
_LOGGING_INITIALIZED: bool = False


def setup_logging(force: bool = False) -> None:
    """
    初始化全局日志。

    - 控制台输出：便于开发期观察
    - 滚动文件：logs/app.log，单文件最大 10MB，保留 5 份备份
    """
    global _LOGGING_INITIALIZED
    if _LOGGING_INITIALIZED and not force:
        return

    settings = get_settings()
    log_dir: Path = settings.log_path
    log_dir.mkdir(parents=True, exist_ok=True)

    level = getattr(logging, settings.log_level.upper(), logging.INFO)
    formatter = logging.Formatter(
        fmt="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    root_logger = logging.getLogger()
    root_logger.setLevel(level)
    # 清空已有 Handler，避免重复输出
    root_logger.handlers.clear()

    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(level)
    console_handler.setFormatter(formatter)
    root_logger.addHandler(console_handler)

    file_handler = RotatingFileHandler(
        filename=str(log_dir / "app.log"),
        maxBytes=10 * 1024 * 1024,
        backupCount=5,
        encoding="utf-8",
    )
    file_handler.setLevel(level)
    file_handler.setFormatter(formatter)
    root_logger.addHandler(file_handler)

    # 降低第三方库噪音
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    logging.getLogger("chromadb").setLevel(logging.WARNING)
    logging.getLogger("urllib3").setLevel(logging.WARNING)

    _LOGGING_INITIALIZED = True
    logging.getLogger(__name__).info(
        "日志系统已初始化，级别=%s，目录=%s",
        settings.log_level,
        log_dir,
    )


def get_logger(name: str) -> logging.Logger:
    """获取模块级 Logger；若尚未初始化则自动初始化。"""
    if not _LOGGING_INITIALIZED:
        setup_logging()
    return logging.getLogger(name)