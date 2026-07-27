# 上海佳得森辉新材料(集团）有限公司RAG 问答 Demo（作者：吴常春）

基于 FastAPI + LangGraph + LlamaIndex + Chroma + Langfuse 的 AI Agent 多轮对话系统。  
本说明面向 **Windows + Docker Desktop + Conda `test` 环境**，按顺序执行即可把项目跑起来。

---

## 目录

1. [环境准备](#1-环境准备)
2. [配置真实 API KEY（修改 .env）](#2-配置真实-api-key修改-env)
3. [在 conda test 环境安装依赖](#3-在-conda-test-环境安装依赖)
4. [用 Docker 启动依赖服务与应用](#4-用-docker-启动依赖服务与应用)
5. [浏览器访问 Web 页面](#5-浏览器访问-web-页面)
6. [构建知识库索引（推荐）](#6-构建知识库索引推荐)
7. [本地开发模式（不用应用容器）](#7-本地开发模式不用应用容器)
8. [常用运维命令](#8-常用运维命令)
9. [常见问题](#9-常见问题)

---

## 1. 环境准备

请确认已安装并可用：

| 组件 | 说明 |
|------|------|
| Docker Desktop | 已启动（托盘图标为 Running） |
| Conda | 已有名为 `test` 的环境（Python 3.11） |
| Git（可选） | 用于克隆或更新代码 |

在 PowerShell 中检查：

```powershell
docker version
docker compose version
conda env list
```

应能看到 `test` 环境，且 Docker 引擎正常。

进入项目根目录：

```powershell
cd D:\wuchch\training\cur0724-RAG
```

---

## 2. 配置真实 API KEY（修改 .env）

项目通过 `.env` 读取密钥与数据库配置。仓库只提供模板 `.env.example`，**不要把填好真实密钥的 `.env` 提交到 Git**。

### 2.1 复制模板

```powershell
copy .env.example .env
```

### 2.2 用编辑器打开 `.env`，至少修改以下项

#### （必填）大模型 API Key

```env
OPENAI_API_KEY=sk-你的真实密钥
OPENAI_API_BASE=https://api.openai.com/v1
LLM_MODEL_NAME=gpt-4o-mini
EMBEDDING_MODEL_NAME=text-embedding-3-small
EMBEDDING_PROVIDER=openai
```

说明：

- 若使用官方 OpenAI，把 `OPENAI_API_KEY` 换成你的真实 `sk-...`。
- 若使用兼容网关（如代理、Azure OpenAI 兼容层、国内中转），同时修改：
  - `OPENAI_API_KEY`
  - `OPENAI_API_BASE`（例如 `https://your-gateway.example.com/v1`）
  - `LLM_MODEL_NAME` / `EMBEDDING_MODEL_NAME`（按网关支持的模型名填写）

#### （强烈建议）应用密钥

```env
APP_SECRET_KEY=请改成一串足够长的随机字符串
```

#### （可选）演示登录账号

默认：

```env
DEMO_USERNAME=admin
DEMO_PASSWORD=admin123
```

首次启动后端时会自动创建该演示用户。

#### （可选）Langfuse

本地演示可先保持模板默认值。若要在 Langfuse 控制台看追踪，启动 compose 后打开 `http://localhost:3000`，用初始化账号登录，再把项目里的公钥/私钥填回：

```env
LANGFUSE_PUBLIC_KEY=pk-lf-...
LANGFUSE_SECRET_KEY=sk-lf-...
LANGFUSE_ENABLED=true
```

#### 数据库连接（一般不用改）

- **本机 conda 跑应用**时，使用模板默认即可：`127.0.0.1:5433`
- **Docker 容器跑应用**时，`docker-compose.yml` 会覆盖为容器内地址 `app-postgres:5432`，无需手改

---

## 3. 在 conda test 环境安装依赖

即使用 Docker 跑应用，也建议在 `test` 环境装好依赖，便于本地建索引、排错。

```powershell
conda activate test
python -V
# 期望类似：Python 3.11.x

cd D:\wuchch\training\cur0724-RAG
pip install -U pip
pip install -r requirements.txt
```

安装时间可能较长（含 `torch`、`sentence-transformers` 等）。若网络较慢，可配置国内 PyPI 镜像后再装。

验证关键包：

```powershell
python -c "import fastapi, langgraph, llama_index, chromadb; print('deps ok')"
```

---

## 4. 用 Docker 启动依赖服务与应用

Docker Desktop 保持运行。在项目根目录执行下列命令。

### 4.1（推荐）先只启动基础设施：Postgres + Langfuse 栈

```powershell
docker compose up -d app-postgres langfuse-web langfuse-worker langfuse-postgres clickhouse redis minio
```

查看状态：

```powershell
docker compose ps
```

业务库映射端口：`127.0.0.1:5433`  
Langfuse UI：`http://localhost:3000`

### 4.2 构建应用镜像（Image）

```powershell
docker build -t rag-agent-app:latest .
```

或用 compose 构建：

```powershell
docker compose build rag-app
```

> 首次构建会 `pip install -r requirements.txt`，耗时与体积都较大，请耐心等待。

### 4.3 创建并启动应用容器（Container）

确保已存在 `.env`（含真实 `OPENAI_API_KEY`），然后：

```powershell
docker compose up -d rag-app
```

等价的手动命令示例（一般优先用 compose）：

```powershell
docker run -d --name rag-agent-app `
  --network cur0724-rag_default `
  -p 8000:8000 `
  --env-file .env `
  -e DATABASE_URL=postgresql+asyncpg://rag_user:rag_password@app-postgres:5432/rag_agent `
  -e APP_POSTGRES_HOST=app-postgres `
  -e APP_POSTGRES_PORT=5432 `
  -v ${PWD}/document:/app/document `
  -v ${PWD}/data:/app/data `
  -v ${PWD}/logs:/app/logs `
  rag-agent-app:latest
```

> 网络名以 `docker network ls` 实际为准（可能是 `cur0724-rag_default`）。用 `docker compose up` 可自动处理网络，更省事。

### 4.4 一键启动全部服务（基础设施 + 应用）

```powershell
docker compose up -d --build
```

### 4.5 查看应用日志

```powershell
docker compose logs -f rag-app
# 或
docker logs -f rag-agent-app
```

看到类似启动完成、无持续报错即可。健康检查：

```powershell
curl http://127.0.0.1:8000/health
```

应返回 `{"status":"ok"}`。

---

## 5. 浏览器访问 Web 页面

| 页面 | 地址 |
|------|------|
| 登录页 | http://localhost:8000/login |
| 主工作区 | http://localhost:8000/ |
| API 文档 | http://localhost:8000/docs |
| Langfuse 监控 | http://localhost:3000 |

### 登录与体验演示

1. 打开 http://localhost:8000/login  
2. 用户名 / 密码：`.env` 中的 `DEMO_USERNAME` / `DEMO_PASSWORD`（默认 `admin` / `admin123`）  
3. 输入图形验证码（看不清可点击验证码图片刷新）  
4. 登录后进入主界面：  
   - 左侧：上传 Word / Markdown，查看文档列表  
   - 右侧：多轮对话（SSE 流式 Markdown）  
5. 页头品牌文案为：  
   **上海佳得森辉新材料(集团）有限公司RAG 问答 Demo（作者：吴常春）**

---

## 6. 构建知识库索引（推荐）

`document/` 下已有样例手册。在 **conda `test` 环境**中构建向量索引（需已配置 `OPENAI_API_KEY`，或改用本地 Embedding）：

```powershell
conda activate test
cd D:\wuchch\training\cur0724-RAG

# 使用 OpenAI Embedding（与 .env 中 EMBEDDING_PROVIDER=openai 一致）
python -m scripts.build_rag_index

# 若暂时没有 API Key，可改用本地模型：
# python -m scripts.build_rag_index --provider local
```

若应用跑在 Docker 里，索引目录 `data/chroma` 已通过 volume 挂载，宿主机建好索引后容器内可直接使用；也可进入容器执行同样命令：

```powershell
docker compose exec rag-app python -m scripts.build_rag_index
```

---

## 7. 本地开发模式（不用应用容器）

适合改代码热重载调试：

```powershell
# 终端 1：只起依赖
docker compose up -d app-postgres langfuse-web langfuse-worker langfuse-postgres clickhouse redis minio

# 终端 2：本机跑 FastAPI
conda activate test
cd D:\wuchch\training\cur0724-RAG
copy .env.example .env   # 若尚未复制
# 编辑 .env 填入真实 OPENAI_API_KEY
uvicorn src.main:app --host 0.0.0.0 --port 8000 --reload
```

浏览器同样访问 http://localhost:8000/login 。

> 此时请**不要**同时再 `up` 占用 8000 端口的 `rag-app` 容器，避免端口冲突。

---

## 8. 常用运维命令

```powershell
# 查看所有容器状态
docker compose ps

# 停止应用容器
docker compose stop rag-app

# 停止并删除应用容器（镜像保留）
docker compose rm -f rag-app

# 重新构建并启动应用
docker compose up -d --build rag-app

# 停止全部 compose 服务
docker compose down

# 停止并删除数据卷（会清空 Postgres/Langfuse 数据，慎用）
docker compose down -v

# 删除应用镜像
docker rmi rag-agent-app:latest
```

HTTPS / Nginx（可选，见阶段五文档）：

```powershell
cd nginx\scripts
powershell -ExecutionPolicy Bypass -File .\gen_self_signed_cert.ps1
# 再按 nginx/SSL_SETUP.md 启动 Nginx，访问 https://localhost/
```

---

## 9. 常见问题

### 9.1 Docker 报错无法连接引擎

确认 Docker Desktop 已启动；PowerShell 执行 `docker version` 应无错误。

### 9.2 `rag-app` 启动后数据库连接失败

先保证 `app-postgres` healthy：

```powershell
docker compose ps app-postgres
docker compose logs app-postgres
```

再重启应用：

```powershell
docker compose up -d rag-app
```

### 9.3 登录提示验证码错误

点击验证码图片刷新后重试；确认系统时间正常。

### 9.4 对话无回复 / 报模型错误

检查 `.env` 中 `OPENAI_API_KEY`、`OPENAI_API_BASE`、`LLM_MODEL_NAME` 是否正确；查看：

```powershell
docker compose logs -f rag-app
```

### 9.5 8000 端口被占用

```powershell
netstat -ano | findstr :8000
docker compose stop rag-app
```

或修改映射，例如 `"8001:8000"`，然后访问 http://localhost:8001 。

### 9.6 构建镜像太慢 / 体积太大

`requirements.txt` 含深度学习相关依赖。可先用「第 7 节本地开发模式」跑通业务；镜像构建建议在网络稳定时执行，并保持 Docker Desktop 资源充足。

---

## 最小可运行路径（抄这段即可）

```powershell
cd D:\wuchch\training\cur0724-RAG

# 1) 配置密钥
copy .env.example .env
notepad .env
# 将 OPENAI_API_KEY 改为真实值并保存

# 2) 安装 Python 依赖（conda test）
conda activate test
pip install -r requirements.txt

# 3) 启动 Docker 依赖 + 构建/启动应用
docker compose up -d app-postgres
docker compose up -d --build rag-app

# 4)（可选）建索引
python -m scripts.build_rag_index

# 5) 浏览器打开
start http://localhost:8000/login
```

默认账号：`admin` / `admin123`。

---

## 项目结构速览

```text
cur0724-RAG/
├── src/                 # 后端（FastAPI / LangGraph / RAG / 工具）
├── templates/           # 登录页、主工作区 HTML
├── static/              # CSS / JS
├── document/            # 初始测试文档
├── nginx/               # HTTPS 反代与自签发证书说明
├── scripts/             # 索引构建脚本
├── docker-compose.yml   # Postgres + Langfuse + rag-app
├── Dockerfile           # 应用镜像
├── .env.example         # 环境变量模板
├── requirements.txt     # Python 依赖
└── README.md            # 本说明
```