# 手工创建 / 自签发 SSL 证书与 Nginx 配置指南

本文说明如何在本地或内网环境**手工生成自签发（Self-Signed）SSL 证书**，并将其配置到本项目的 Nginx 反向代理中，使 FastAPI 服务通过 HTTPS 对外提供访问。

> 说明：自签发证书适用于开发、演示与内网环境。浏览器会提示“连接不是私密连接”，选择继续访问即可。生产公网环境请改用正式 CA 证书（如 Let's Encrypt）。

---

## 1. 目录约定

在项目根目录下：

```text
nginx/
├── nginx.conf          # Nginx 主配置（已含 HTTPS 反代）
├── SSL_SETUP.md        # 本说明
├── ssl/
│   ├── server.crt      # 证书（公钥）
│   ├── server.key      # 私钥（保密）
│   └── openssl.cnf     # 可选：扩展配置
└── scripts/
    ├── gen_self_signed_cert.sh   # Linux / macOS / Git Bash
    └── gen_self_signed_cert.ps1  # Windows PowerShell
```

证书路径需与 `nginx.conf` 中以下两项一致：

```nginx
ssl_certificate     /etc/nginx/ssl/server.crt;
ssl_certificate_key /etc/nginx/ssl/server.key;
```

若在宿主机直接运行 Nginx（非容器），请改为本机绝对路径，例如：

```nginx
ssl_certificate     D:/wuchch/training/cur0724-RAG/nginx/ssl/server.crt;
ssl_certificate_key D:/wuchch/training/cur0724-RAG/nginx/ssl/server.key;
```

---

## 2. 前置条件

1. 已安装 OpenSSL：
   - Windows：可使用 Git Bash 自带的 `openssl`，或安装 Win64 OpenSSL
   - Linux：`sudo apt install openssl` / `sudo yum install openssl`
   - macOS：系统一般自带，或 `brew install openssl`
2. FastAPI 已在本机监听：`http://127.0.0.1:8000`
3. 已安装 Nginx（系统包或 Docker 镜像 `nginx:1.27`）

---

## 3. 一键脚本生成证书（推荐）

### 3.1 Windows（PowerShell）

在项目根目录执行：

```powershell
cd nginx/scripts
powershell -ExecutionPolicy Bypass -File .\gen_self_signed_cert.ps1
```

默认会在 `nginx/ssl/` 生成：

- `server.key`：私钥
- `server.crt`：自签发证书（有效期 825 天）

可选参数：

```powershell
.\gen_self_signed_cert.ps1 -CommonName "rag.local" -Days 825
```

### 3.2 Linux / macOS / Git Bash

```bash
cd nginx/scripts
chmod +x gen_self_signed_cert.sh
./gen_self_signed_cert.sh
# 或指定域名
./gen_self_signed_cert.sh rag.local 825
```

---

## 4. 手工命令行步骤（逐步理解）

以下命令在项目根目录执行，效果与脚本等价。

### 步骤 A：进入证书目录

```bash
mkdir -p nginx/ssl
cd nginx/ssl
```

Windows PowerShell：

```powershell
New-Item -ItemType Directory -Force -Path nginx\ssl | Out-Null
Set-Location nginx\ssl
```

### 步骤 B：生成私钥（RSA 2048）

```bash
openssl genrsa -out server.key 2048
```

### 步骤 C：生成证书签名请求 CSR

将 `CN` 换成你的域名或主机名（本机可用 `localhost`）：

```bash
openssl req -new -key server.key -out server.csr -subj "/C=CN/ST=Shanghai/L=Shanghai/O=Jadeson/OU=RAG/CN=localhost"
```

### 步骤 D：用私钥自签发证书（X.509）

```bash
openssl x509 -req -days 825 -in server.csr -signkey server.key -out server.crt
```

### 步骤 E（可选）：为 localhost / 内网 IP 添加 SAN

现代浏览器更认 Subject Alternative Name。可先写扩展文件 `openssl-san.cnf`：

```ini
[req]
distinguished_name = req_distinguished_name
x509_extensions = v3_req
prompt = no

[req_distinguished_name]
C = CN
ST = Shanghai
L = Shanghai
O = Jadeson
OU = RAG
CN = localhost

[v3_req]
keyUsage = digitalSignature, keyEncipherment
extendedKeyUsage = serverAuth
subjectAltName = @alt_names

[alt_names]
DNS.1 = localhost
DNS.2 = rag.local
IP.1 = 127.0.0.1
```

然后一条命令完成：

```bash
openssl req -x509 -nodes -newkey rsa:2048 -days 825 \
  -keyout server.key -out server.crt \
  -config openssl-san.cnf -extensions v3_req
```

### 步骤 F：校验证书内容

```bash
openssl x509 -in server.crt -noout -text | more
```

确认：

- `Subject` / `CN` 正确
- `Not After` 未过期
- 若使用 SAN，`X509v3 Subject Alternative Name` 含 `localhost`

---

## 5. 将证书配置到 Nginx

1. 确认文件存在：
   - `nginx/ssl/server.crt`
   - `nginx/ssl/server.key`
2. 打开 `nginx/nginx.conf`，检查：
   - `server_name` 是否与证书 CN/SAN 一致
   - `ssl_certificate` / `ssl_certificate_key` 路径是否可达
   - `proxy_pass` 是否指向 FastAPI（默认 `http://127.0.0.1:8000`）
3. 检查配置语法：

```bash
nginx -t -c /path/to/nginx.conf
```

4. 启动或重载：

```bash
nginx -c /path/to/nginx.conf
# 或
nginx -s reload
```

### 使用 Docker 运行 Nginx（示例）

在项目根目录：

```bash
docker run -d --name rag-nginx --network host \
  -v "%cd%/nginx/nginx.conf:/etc/nginx/nginx.conf:ro" \
  -v "%cd%/nginx/ssl:/etc/nginx/ssl:ro" \
  nginx:1.27
```

Linux 上 `--network host` 可使容器直接访问宿主机 `127.0.0.1:8000`。  
Windows / macOS Docker Desktop 不支持 host 网络时，请将 `nginx.conf` 中上游改为：

```nginx
set $upstream_fastapi http://host.docker.internal:8000;
```

并改用端口映射：

```bash
docker run -d --name rag-nginx -p 80:80 -p 443:443 \
  -v "${PWD}/nginx/nginx.conf:/etc/nginx/nginx.conf:ro" \
  -v "${PWD}/nginx/ssl:/etc/nginx/ssl:ro" \
  nginx:1.27
```

---

## 6. 验证 HTTPS 是否生效

1. 启动 FastAPI：

```bash
conda activate test
uvicorn src.main:app --host 0.0.0.0 --port 8000
```

2. 启动 Nginx（已加载证书）。
3. 浏览器访问：`https://localhost/`
4. 若提示证书不受信任：属自签发正常现象，选择“继续访问”。
5. 检查反代与 SSE：
   - 打开登录页，完成登录
   - 发起对话，确认流式输出正常（`nginx.conf` 已对 `/api/v1/chat/stream` 关闭缓冲）

命令行快速探测：

```bash
curl -k https://localhost/health
curl -k -I https://localhost/login
```

`-k` 表示忽略自签发证书校验。

---

## 7. 权限与安全建议

1. **私钥权限**：Linux 下建议 `chmod 600 nginx/ssl/server.key`
2. **不要提交私钥到 Git**：将 `nginx/ssl/*.key`、`*.crt` 加入 `.gitignore`
3. **仅内网演示**：自签发证书勿用于公网生产
4. **正式环境**：使用 Let's Encrypt（certbot）或企业证书，并定期轮换

`.gitignore` 建议追加：

```gitignore
nginx/ssl/*.key
nginx/ssl/*.crt
nginx/ssl/*.csr
nginx/ssl/*.pem
```

---

## 8. 常见问题

| 现象 | 可能原因 | 处理 |
|------|----------|------|
| 浏览器报 NET::ERR_CERT_AUTHORITY_INVALID | 自签发未被系统信任 | 开发环境点继续；或导入系统信任根 |
| 502 Bad Gateway | FastAPI 未启动或上游地址错误 | 检查 8000 端口与 `proxy_pass` |
| 对话没有流式效果 | SSE 被缓冲 | 确认命中 `/api/v1/chat/stream` 且 `proxy_buffering off` |
| nginx -t 报证书找不到 | 路径未挂载或写错 | 核对容器内 `/etc/nginx/ssl` 或本机绝对路径 |

---

## 9. 与本项目联调检查清单

1. [ ] `nginx/ssl/server.crt` 与 `server.key` 已生成
2. [ ] `nginx.conf` 中 `server_name`、证书路径、上游地址已按环境修改
3. [ ] FastAPI：`uvicorn src.main:app --host 0.0.0.0 --port 8000`
4. [ ] Nginx 已启动且 `nginx -t` 通过
5. [ ] `https://localhost/login` 可打开并登录
6. [ ] 流式问答与文件上传经 HTTPS 正常工作