# =============================================================================
# RAG Agent 应用镜像
# 构建：docker build -t rag-agent-app:latest .
# 运行：见 README.md
# =============================================================================

FROM python:3.11-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_INDEX_URL=https://mirrors.aliyun.com/pypi/simple/ \
    PIP_TRUSTED_HOST=mirrors.aliyun.com

WORKDIR /app

# 更换为清华源（速度稳定）
RUN sed -i 's/deb.debian.org/mirrors.tuna.tsinghua.edu.cn/g' /etc/apt/sources.list.d/debian.sources \
    && sed -i 's/deb.debian.org/mirrors.tuna.tsinghua.edu.cn/g' /etc/apt/sources.list 2>/dev/null || true

# 编译部分 Python 包所需的系统依赖
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    curl \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
# 阿里云 PyPI + 阿里云 PyTorch CPU 轮子（见 requirements.txt 中 -f）
RUN pip install --upgrade pip \
    && pip install --retries 5 --timeout 600 -r requirements.txt

# 复制项目代码（.dockerignore 会排除无关大文件）
COPY . .

# 运行期目录
RUN mkdir -p /app/data/chroma /app/data/uploads /app/logs /app/document

EXPOSE 8000

# 健康检查（可选）
HEALTHCHECK --interval=30s --timeout=5s --start-period=40s --retries=3 \
  CMD curl -fsS http://127.0.0.1:8000/health || exit 1

CMD ["uvicorn", "src.main:app", "--host", "0.0.0.0", "--port", "8000"]