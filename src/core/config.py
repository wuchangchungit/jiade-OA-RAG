# =============================================================================
# 应用配置模块
# 从环境变量 / .env 加载配置，供 RAG、工具及其他模块统一引用
# =============================================================================

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


# 项目根目录：src/core/config.py -> 上溯三级
PROJECT_ROOT: Path = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    """全局配置类，字段与 .env.example 保持对应关系。"""

    model_config = SettingsConfigDict(
        env_file=str(PROJECT_ROOT / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # ----- 应用基础 -----
    app_env: str = Field(default="development", description="运行环境")
    log_level: str = Field(default="INFO", description="日志级别")
    log_dir: str = Field(default="logs", description="日志目录（相对项目根）")

    # ----- 大模型 -----
    openai_api_key: str = Field(default="", description="OpenAI 兼容 API Key")
    openai_api_base: str = Field(
        default="https://api.openai.com/v1",
        description="OpenAI 兼容 API Base URL",
    )
    llm_model_name: str = Field(default="gpt-4o-mini", description="对话模型名")
    embedding_model_name: str = Field(
        default="text-embedding-3-small",
        description="OpenAI Embedding 模型名",
    )
    # local: 使用 sentence-transformers；openai: 使用远程 Embedding API
    embedding_provider: Literal["openai", "local"] = Field(
        default="openai",
        description="向量化提供方",
    )
    local_embedding_model: str = Field(
        default="sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2",
        description="本地 Embedding 模型（embedding_provider=local 时生效）",
    )
    # DashScope text-embedding 单次 batch 上限为 20；官方 OpenAI 可更大
    embedding_batch_size: int = Field(
        default=10,
        ge=1,
        le=100,
        description="Embedding 请求批大小（阿里云兼容接口建议 ≤20）",
    )

    # ----- Chroma -----
    chroma_persist_dir: str = Field(default="data/chroma", description="Chroma 持久化目录")
    chroma_collection_name: str = Field(
        default="ems_handbook_collection",
        description="Chroma 集合名称",
    )

    # ----- RAG 路径与分片 -----
    document_dir: str = Field(default="document", description="初始测试文档目录")
    upload_dir: str = Field(default="data/uploads", description="上传文档目录")
    rag_parent_chunk_size: int = Field(default=2048, description="父块字符数")
    rag_child_chunk_size: int = Field(default=512, description="子块字符数")
    rag_retrieve_top_k: int = Field(default=20, description="混合检索召回数量")
    rag_rerank_top_n: int = Field(default=5, description="重排序后返回数量")
    # Docker 内常无法访问 HuggingFace；默认关闭，有本地模型缓存时可设 true
    rag_enable_rerank: bool = Field(
        default=False,
        description="是否启用 CrossEncoder 重排序",
    )
    # 本地 CrossEncoder 重排序模型
    rerank_model_name: str = Field(
        default="BAAI/bge-reranker-base",
        description="重排序模型名称",
    )
    # RAG 工具执行超时（秒）；冷启动建索引/下载模型时 5s 不够
    rag_tool_timeout_seconds: float = Field(
        default=60.0,
        ge=5.0,
        description="ems_handbook_tool 执行超时秒数",
    )
    # ----- 服务监听 -----
    app_host: str = Field(default="0.0.0.0", description="FastAPI 监听地址")
    app_port: int = Field(default=8000, description="FastAPI 监听端口")
    app_secret_key: str = Field(
        default="please_change_this_to_a_long_random_string",
        description="应用密钥（JWT 签名等）",
    )

    # ----- 业务数据库 -----
    database_url: str = Field(
        default="postgresql+asyncpg://rag_user:rag_password@127.0.0.1:5433/rag_agent",
        description="异步数据库连接串",
    )
    database_url_sync: str = Field(
        default="postgresql+psycopg2://rag_user:rag_password@127.0.0.1:5433/rag_agent",
        description="同步数据库连接串",
    )

    # ----- 认证 -----
    jwt_expire_minutes: int = Field(default=1440, description="JWT 过期时间（分钟）")
    captcha_expire_seconds: int = Field(default=300, description="验证码有效期（秒）")
    captcha_fixed_code: str = Field(
        default="1234",
        description="固定验证码；非空则始终使用该值（演示/手机端方便）；置空则随机生成",
    )
    demo_username: str = Field(default="admin", description="演示账号用户名")
    demo_password: str = Field(default="admin123", description="演示账号密码")

    # ----- Agent -----
    max_tool_calls: int = Field(default=3, description="单轮最大工具调用次数")
    chat_history_window: int = Field(default=10, description="历史对话保留轮数")
    user_query_max_chars: int = Field(default=2000, description="用户单次输入最大字符数")

    def resolve_path(self, relative: str) -> Path:
        """将相对路径解析为基于项目根目录的绝对路径。"""
        path = Path(relative)
        if path.is_absolute():
            return path
        return PROJECT_ROOT / path

    @property
    def chroma_path(self) -> Path:
        """Chroma 持久化绝对路径。"""
        return self.resolve_path(self.chroma_persist_dir)

    @property
    def document_path(self) -> Path:
        """测试文档目录绝对路径。"""
        return self.resolve_path(self.document_dir)

    @property
    def upload_path(self) -> Path:
        """上传目录绝对路径。"""
        return self.resolve_path(self.upload_dir)

    @property
    def log_path(self) -> Path:
        """日志目录绝对路径。"""
        return self.resolve_path(self.log_dir)


@lru_cache
def get_settings() -> Settings:
    """获取单例配置对象（进程内缓存）。"""
    return Settings()