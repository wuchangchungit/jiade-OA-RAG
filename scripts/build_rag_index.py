# =============================================================================
# 脚本：从 document/ 目录构建 RAG 向量索引
# 用法（在项目根目录、conda test 环境中）:
#   conda activate test
#   python -m scripts.build_rag_index
#   python -m scripts.build_rag_index --provider local
# =============================================================================

from __future__ import annotations

import argparse
import sys
from pathlib import Path

# 保证项目根目录在 sys.path 中，便于 python -m scripts.build_rag_index
PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.core.config import get_settings
from src.core.logging_config import get_logger, setup_logging
from src.rag.pipeline import RAGPipeline


def parse_args() -> argparse.Namespace:
    """解析命令行参数。"""
    parser = argparse.ArgumentParser(description="构建 EMS 手册 RAG 向量索引")
    parser.add_argument(
        "--dir",
        type=str,
        default=None,
        help="文档目录，默认读取配置中的 DOCUMENT_DIR",
    )
    parser.add_argument(
        "--provider",
        type=str,
        choices=["openai", "local"],
        default=None,
        help="Embedding 提供方，覆盖 .env 中的 EMBEDDING_PROVIDER",
    )
    parser.add_argument(
        "--no-replace",
        action="store_true",
        help="增量构建（不清空已有 Chroma 集合）",
    )
    return parser.parse_args()


def main() -> int:
    """入口：构建索引并打印简要状态。"""
    args = parse_args()
    setup_logging()
    logger = get_logger("scripts.build_rag_index")

    settings = get_settings()
    if args.provider:
        # 运行时覆盖 Embedding 提供方（不写回 .env）
        settings = settings.model_copy(update={"embedding_provider": args.provider})

    logger.info(
        "准备构建索引，document_dir=%s，provider=%s，replace=%s",
        args.dir or settings.document_path,
        settings.embedding_provider,
        not args.no_replace,
    )

    pipeline = RAGPipeline(settings=settings)
    try:
        pipeline.build_index(directory=args.dir, replace=not args.no_replace)
    except Exception as exc:  # noqa: BLE001
        logger.exception("索引构建失败: %s", exc)
        return 1

    count = pipeline.indexer._chroma_collection.count()  # noqa: SLF001
    logger.info("索引构建成功，Chroma 当前文档数=%d", count)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())