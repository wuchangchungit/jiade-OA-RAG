# =============================================================================
# Embedding 工厂
# 根据配置创建 OpenAI 或本地 HuggingFace Embedding
# =============================================================================

from __future__ import annotations

from llama_index.core.embeddings import BaseEmbedding

from src.core.config import Settings, get_settings
from src.core.logging_config import get_logger

logger = get_logger(__name__)


def build_embed_model(settings: Settings | None = None) -> BaseEmbedding:
    """
    根据 settings.embedding_provider 构建 Embedding 模型。

    - openai: 调用远程 Embedding API（需配置 OPENAI_API_KEY）
    - local:  使用 sentence-transformers 本地模型（适合离线/无 Key 调试）
    """
    settings = settings or get_settings()

    if settings.embedding_provider == "local":
        from llama_index.embeddings.huggingface import HuggingFaceEmbedding

        logger.info(
            "使用本地 Embedding 模型: %s",
            settings.local_embedding_model,
        )
        return HuggingFaceEmbedding(model_name=settings.local_embedding_model)

    from llama_index.embeddings.openai import OpenAIEmbedding

    if not settings.openai_api_key:
        logger.warning(
            "OPENAI_API_KEY 为空，OpenAI Embedding 可能调用失败；"
            "可设置 EMBEDDING_PROVIDER=local 使用本地模型"
        )

    logger.info(
        "使用 OpenAI Embedding 模型: %s, base=%s, batch=%s",
        settings.embedding_model_name,
        settings.openai_api_base,
        settings.embedding_batch_size,
    )
    # 必须用 model_name= 而非 model=：后者会校验 OpenAIEmbeddingModelType 枚举，
    # 导致阿里云等兼容网关的模型名（如 text-embedding-v4）在发请求前就失败。
    # embed_batch_size 默认 ≤20：DashScope 限制单次 input.contents 不超过 20。
    return OpenAIEmbedding(
        model_name=settings.embedding_model_name,
        api_key=settings.openai_api_key or None,
        api_base=settings.openai_api_base or None,
        embed_batch_size=settings.embedding_batch_size,
    )