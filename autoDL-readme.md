# AutoDL 迁移与运行说明

本文说明如何把本项目从本机（Windows）迁移到 **AutoDL Linux 实例** 并跑起来。

**核心原则（针对无 Docker 命令的 AutoDL 环境）：**

- AutoDL 实例本身已是 Linux，**不要**再 `docker build` / `docker compose` / 启动 `rag-app`。
- 业务应用：用 **venv + uvicorn** 直接跑。
- 业务数据库：在实例内 **原生安装 PostgreSQL**（不用 Docker）。
- Langfuse：无 Docker 时 **默认关闭**（不影响登录与问答）；需要监控可另外部署。

---

## 目录

1. [迁移前准备](#1-迁移前准备)
2. [上传项目到 AutoDL](#2-上传项目到-autodl)
3. [安装并初始化 PostgreSQL（无 Docker）](#3-安装并初始化-postgresql无-docker)
4. [配置 .env](#4-配置-env)
5. [安装 Python 依赖](#5-安装-python-依赖)
6. [启动业务应用（uvicorn）](#6-启动业务应用uvicorn)
7. [浏览器访问（AutoDL 端口）](#7-浏览器访问autodl-端口)
8. [构建 / 重建知识库索引（可选）](#8-构建--重建知识库索引可选)
9. [日常运维](#9-日常运维)
10. [常见问题](#10-常见问题)

---

## 1. 迁移前准备

### 1.1 本机打包（推荐）

在项目根目录（Windows PowerShell）：

```powershell
cd D:\wuchch\training\cur0724-RAG

# 建议不要把含真实密钥的 .env 打进包；密钥单独拷贝
tar -czvf cur0724-RAG-autodl.tgz `
  --exclude=.git `
  --exclude=__pycache__ `
  --exclude=*.pyc `
  --exclude=.venv `
  --exclude=node_modules `
  .
```

或使用 Git：

```bash
git clone <你的仓库地址> cur0724-RAG
```

### 1.2 AutoDL 实例建议

| 项 | 建议 |
|----|------|
| 系统 | Ubuntu / 常见 PyTorch 镜像均可 |
| 磁盘 | 项目与数据放在 `/root/autodl-tmp`（关机保留） |
| Docker | **本说明不使用 Docker** |
| 端口 | 业务 Web 建议监听 **6006**（自定义服务常用口） |

检查：

```bash
python3 -V          # 建议 3.10 / 3.11
which docker || echo "无 docker，按本文原生安装 Postgres"
```

---

## 2. 上传项目到 AutoDL

### 方式 A：控制台上传

1. AutoDL → JupyterLab / 文件面板  
2. 上传 `cur0724-RAG-autodl.tgz` 到 `/root/autodl-tmp/`  
3. 终端解压：

```bash
cd /root/autodl-tmp
mkdir -p cur0724-RAG
tar -xzvf cur0724-RAG-autodl.tgz -C cur0724-RAG
cd /root/autodl-tmp/cur0724-RAG
ls
```

### 方式 B：本机 scp

```powershell
scp -P <SSH端口> cur0724-RAG-autodl.tgz root@<SSH主机>:/root/autodl-tmp/
```

登录实例后解压同上。

### 方式 C：Git clone

```bash
cd /root/autodl-tmp
git clone <仓库地址> cur0724-RAG
cd cur0724-RAG
```

---

## 3. 安装并初始化 PostgreSQL（无 Docker）

业务登录、会话、文档元数据依赖 PostgreSQL。在 AutoDL 实例内原生安装即可。

### 3.1 安装（Ubuntu / Debian 系）

```bash
apt-get update 
DEBIAN_FRONTEND=noninteractive apt-get install -y postgresql postgresql-contrib
```

若 `apt-get` 提示权限不足，前面加 `sudo`（多数 AutoDL 镜像已是 root）。

### 3.2 启动服务

```bash
# 常见两种写法，按实际环境选用
service postgresql start
# 或
# systemctl start postgresql

# 确认 Postgres 已就绪（AutoDL 常无 ss/netstat，不要用它们）
pg_isready -h 127.0.0.1 -p 5432
# 期望输出类似：127.0.0.1:5432 - accepting connections

# 若没有 pg_isready，可用 Python 探测端口：
python3 -c "import socket; s=socket.create_connection(('127.0.0.1',5432),3); s.close(); print('5432 ok')"
```

### 3.3 创建业务用户与数据库

与项目默认账号一致（可按需修改，但需与 `.env` 同步）：

```bash
# 切换到 postgres 系统用户执行
# 不必单独做成脚本文件。这段可以直接整段粘贴到 AutoDL 终端执行（从 su - postgres 到结尾的 SQL 一起贴）。
su - postgres -c "psql -v ON_ERROR_STOP=1" <<'SQL'
DO $$
BEGIN
  IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'rag_user') THEN
    CREATE ROLE rag_user LOGIN PASSWORD 'rag_password';
  END IF;
END
$$;

SELECT 'CREATE DATABASE rag_agent OWNER rag_user'
WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname = 'rag_agent')\gexec

GRANT ALL PRIVILEGES ON DATABASE rag_agent TO rag_user;
SQL
```

若 `\gexec` 报错，可拆成两步：

```bash
su - postgres -c "psql -c \"CREATE USER rag_user WITH PASSWORD 'rag_password';\"" || true
su - postgres -c "psql -c \"CREATE DATABASE rag_agent OWNER rag_user;\"" || true
su - postgres -c "psql -c \"GRANT ALL PRIVILEGES ON DATABASE rag_agent TO rag_user;\""
```

然后验证（看到 1 就说明库建好了。）
PGPASSWORD=rag_password psql -h 127.0.0.1 -p 5432 -U rag_user -d rag_agent -c 'SELECT 1;'


### 3.4 允许本机密码登录（若连不上再改）

编辑 `cd /etc/postgresql/14/main/pg_hba.conf`（路径因版本而异，常见如下）：

```bash
# 查找配置文件
su - postgres -c "psql -c 'SHOW hba_file;'"
```

确保有类似行（本地用密码）：

```text
local   all   rag_user   md5
host    all   rag_user   127.0.0.1/32   md5
host    all   rag_user   ::1/128        md5
```

改完后：

```bash
service postgresql reload
# 或
service postgresql restart
```

### 3.5 验证连接

```bash
PGPASSWORD=rag_password psql -h 127.0.0.1 -p 5432 -U rag_user -d rag_agent -c 'SELECT 1;'
```

成功应看到 `1`。

> 数据目录默认在系统路径。若希望库文件也落在 `/root/autodl-tmp`，需自行改 PostgreSQL `data_directory`（进阶，可选）。日常把项目与 `data/chroma`、`data/uploads` 放在 autodl-tmp 即可。

---

## 4. 配置 .env

```bash
cd /root/autodl-tmp/cur0724-RAG
cp .env.example .env
nano .env
```

### 4.1 必改：大模型（可用阿里云百炼 / DashScope）

```env
OPENAI_API_KEY=sk-你的DashScope密钥
OPENAI_API_BASE=https://dashscope.aliyuncs.com/compatible-mode/v1
LLM_MODEL_NAME=qwen-plus
EMBEDDING_MODEL_NAME=text-embedding-v4
EMBEDDING_PROVIDER=openai
EMBEDDING_BATCH_SIZE=10
```

### 4.2 强烈建议

```env
APP_SECRET_KEY=换成一串足够长的随机字符串
APP_HOST=0.0.0.0
APP_PORT=6006
```

> AutoDL 对外常用 **6006**。

### 4.3 稳定性相关

```env
RAG_ENABLE_RERANK=false
RAG_TOOL_TIMEOUT_SECONDS=60
DEMO_USERNAME=admin
DEMO_PASSWORD=admin123
LANGFUSE_ENABLED=false
CAPTCHA_FIXED_CODE=1234
```

说明：

- 无 Docker 时 **关闭 Langfuse**（`LANGFUSE_ENABLED=false`），不影响演示问答。  
- AutoDL 访问 HuggingFace 常不稳定，**关闭重排序**。  
- 演示账号首次启动应用时会自动创建。

### 4.4 数据库连接（原生 Postgres，端口 5432）

**注意：** 本机 Windows Docker 映射用的是 `5433`；AutoDL 原生 Postgres 默认是 **5432**。

```env
APP_POSTGRES_USER=rag_user
APP_POSTGRES_PASSWORD=rag_password
APP_POSTGRES_DB=rag_agent
APP_POSTGRES_HOST=127.0.0.1
APP_POSTGRES_PORT=5432

DATABASE_URL=postgresql+asyncpg://rag_user:rag_password@127.0.0.1:5432/rag_agent
DATABASE_URL_SYNC=postgresql+psycopg2://rag_user:rag_password@127.0.0.1:5432/rag_agent
```

---

## 5. 安装 Python 依赖

**不要执行**任何 `docker build` / `docker compose`。

```bash
cd /root/autodl-tmp/cur0724-RAG

python3 -m venv .venv
source .venv/bin/activate
python -V

pip install -U pip
pip install -r requirements.txt -i https://mirrors.aliyun.com/pypi/simple/ --trusted-host mirrors.aliyun.com
```

说明：

- `requirements.txt` 已配置 **CPU 版 torch**，无独显也可装。  
- 若 pip 找 torch 失败，确认文件中仍有：  
  `-f https://mirrors.aliyun.com/pytorch-wheels/cpu`  
  与 `torch==2.11.0+cpu`（以你仓库实际版本为准）。

验证：

```bash
python -c "import fastapi, langgraph, llama_index, chromadb, asyncpg; print('deps ok')"
```

---

## 6. 启动业务应用（uvicorn）

先确保 Postgres 已启动：

```bash
service postgresql start
```

再启动应用：

```bash
cd /root/autodl-tmp/cur0724-RAG
source .venv/bin/activate
mkdir -p logs data/chroma data/uploads

# 前台调试
uvicorn src.main:app --host 0.0.0.0 --port 6006

# 或后台
nohup uvicorn src.main:app --host 0.0.0.0 --port 6006 > logs/uvicorn.out 2>&1 &
```

健康检查：

```bash
curl -s http://127.0.0.1:6006/health
# 期望：{"status":"ok"}
```

---

## 7. 浏览器访问（AutoDL 端口）

### 方案 A：自定义服务（推荐，端口 6006）

1. 应用已监听 `0.0.0.0:6006`  
2. AutoDL 控制台 → 实例 → **自定义服务** → 复制 **6006** 地址  

https://u942675-bb52-179c1373.westd.seetacloud.com:8443

3. 打开：

| 页面 | 路径 |
|------|------|
| 登录 | `https://你的映射域名:端口/login` |
| 主工作区 | `https://你的映射域名:端口/` |
| API 文档 | `https://你的映射域名:端口/docs` |

默认登录：

- 用户名：`admin`  
- 密码：`admin123`  
- 验证码：固定为 **`1234`**（由 `CAPTCHA_FIXED_CODE` 控制；图片也会显示该值）

> 个人账号若无法直接开放端口，用方案 B。

### 方案 B：SSH 隧道（本机浏览器）

在 **Windows 本机**：

```powershell
ssh -CNg -L 6006:127.0.0.1:6006 root@<SSH主机> -p <SSH端口>
```

浏览器打开：http://127.0.0.1:6006/login

---

## 8. 构建 / 重建知识库索引（可选）

Web 左侧上传文档即可。脚本方式：

```bash
cd /root/autodl-tmp/cur0724-RAG
source .venv/bin/activate

python -m scripts.build_rag_index
# 或：python -m scripts.build_rag_index --provider local

# 索引损坏时，按库中文档重建：
# python -m scripts.rebuild_ready_index
```

持久化目录（建议在项目下，随 autodl-tmp 保留）：

- `data/chroma`：向量库  
- `data/uploads`：上传文件  
- `logs`：日志  

---

## 9. 日常运维

```bash
cd /root/autodl-tmp/cur0724-RAG

# Postgres
service postgresql status
service postgresql start
service postgresql stop

# 应用日志
tail -f logs/app.log
tail -f logs/uvicorn.out

# 重启应用
pkill -f "uvicorn src.main:app" || true
source .venv/bin/activate
nohup uvicorn src.main:app --host 0.0.0.0 --port 6006 > logs/uvicorn.out 2>&1 &
```

改代码后只需重启 uvicorn，**无需**任何 Docker 镜像构建。

---

## 10. 常见问题

### 10.1 为什么整篇文档都不用 Docker？

当前 AutoDL 环境没有 `docker` 命令。业务用 Python 进程即可；数据库用系统包安装的 PostgreSQL。

### 10.2 `ss` / `netstat: command not found`

AutoDL 精简镜像常不带这些工具，**不必安装**。用：

```bash
pg_isready -h 127.0.0.1 -p 5432
# 或
PGPASSWORD=rag_password psql -h 127.0.0.1 -p 5432 -U rag_user -d rag_agent -c 'SELECT 1;'
```

### 10.3 `psql: could not connect` / 密码认证失败

1. `service postgresql start`  
2. 确认 `.env` 端口是 **5432**（不是 5433）  
3. 检查用户/库是否创建成功  
4. 检查 `pg_hba.conf` 是否允许 `rag_user` 用 md5/scram 从 `127.0.0.1` 连接  

### 10.4 `apt-get install postgresql` 很慢或失败

换镜像源或重试；也可尝试：

```bash
conda install -y -c conda-forge postgresql
# 再用 conda 环境中的 initdb / pg_ctl 建库（步骤因 conda 布局而异）
```

优先用系统 `apt` 安装更省事。

### 10.5 浏览器打不开页面

- uvicorn 必须 `--host 0.0.0.0 --port 6006`  
- 实例内 `curl http://127.0.0.1:6006/health` 先自测  
- 个人账号优先 SSH 隧道  

### 10.6 对话卡住 / 检索超时

- 避免同时后台索引超大 Word  
- 保持 `RAG_ENABLE_RERANK=false`  
- 查看 `logs/app.log`  

### 10.7 Embedding 报错

- DashScope：`EMBEDDING_BATCH_SIZE` ≤ 20（建议 10）  
- `OPENAI_API_BASE=https://dashscope.aliyuncs.com/compatible-mode/v1`  

### 10.8 还要 Langfuse 怎么办？

无 Docker 时本机无法一键起 Langfuse 全套。可选：

1. 演示阶段关闭（推荐）：`LANGFUSE_ENABLED=false`  
2. 使用 Langfuse 云服务，把公钥/私钥与 Host 填进 `.env`  
3. 另找带 Docker 的机器部署 Langfuse，应用只连远程地址  

### 10.9 关机后再开机（最常见：登录 Internal Server Error）

AutoDL **不会**自动拉起本机 PostgreSQL / uvicorn。日志里若出现：

`ConnectionRefusedError: [Errno 111] Connection refused`

说明 **Postgres 未启动**（验证码、登录都要连库，会一起挂）。

按顺序执行：

```bash
# 1) 启动数据库
service postgresql start
# 若提示找不到 service，可试：
# pg_ctlcluster $(pg_lsclusters -h | awk 'NR==1{print $1,$2}') start
# 或：su - postgres -c "/usr/lib/postgresql/*/bin/pg_ctl -D /var/lib/postgresql/*/main start"

# 2) 确认可连
pg_isready -h 127.0.0.1 -p 5432
PGPASSWORD=rag_password psql -h 127.0.0.1 -p 5432 -U rag_user -d rag_agent -c 'SELECT 1;'

# 3) 重启应用（先停旧进程再起）
cd /root/autodl-tmp/cur0724-RAG
pkill -f "uvicorn src.main:app" || true
source .venv/bin/activate
mkdir -p logs
nohup uvicorn src.main:app --host 0.0.0.0 --port 6006 > logs/uvicorn.out 2>&1 &

# 4) 自检
sleep 2
curl -s http://127.0.0.1:6006/health
```

项目与 `data/` 在 `/root/autodl-tmp` 一般会保留；**每次开机都要重新执行上面 1～3 步**。

---

## 快速检查清单

- [ ] 代码在 `/root/autodl-tmp/cur0724-RAG`
- [ ] 已 `apt` 安装并启动 PostgreSQL，`psql` 可连 `rag_agent`
- [ ] `.env`：API Key、`APP_PORT=6006`、数据库端口 **5432**、`LANGFUSE_ENABLED=false`
- [ ] `pip install -r requirements.txt` 成功
- [ ] **没有**使用任何 docker / compose / build rag-app
- [ ] `uvicorn ... --port 6006` 已启动，`/health` 正常
- [ ] 自定义服务或 SSH 隧道可打开 `/login`
- [ ] 可用 `admin` / `admin123` 登录并提问

---

## 与本机 Windows 流程对照

| 本机 Windows | AutoDL（无 Docker） |
|--------------|---------------------|
| Docker Desktop + compose | **不用 Docker** |
| `app-postgres` 容器（宿主机端口 5433） | 系统安装 PostgreSQL（端口 **5432**） |
| Langfuse 全套 compose | 默认关闭 Langfuse |
| 应用容器 `rag-app` | 实例内 `uvicorn` |
| 访问 `localhost:8000` | 访问 **6006** 映射或 SSH 隧道 |

按本文顺序执行即可。若某步报错，保留终端完整输出与 `logs/app.log` 末尾便于继续排查。
