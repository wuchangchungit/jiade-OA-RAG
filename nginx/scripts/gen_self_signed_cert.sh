#!/usr/bin/env bash
# =============================================================================
# 生成 Nginx 自签发 SSL 证书（Linux / macOS / Git Bash）
# 用法：
#   ./gen_self_signed_cert.sh [CommonName] [Days]
# 示例：
#   ./gen_self_signed_cert.sh localhost 825
# =============================================================================

set -euo pipefail

CN="${1:-localhost}"
DAYS="${2:-825}"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SSL_DIR="$(cd "${SCRIPT_DIR}/../ssl" && pwd)"
CNF="${SSL_DIR}/openssl-san.cnf"
OUT_KEY="${SSL_DIR}/server.key"
OUT_CRT="${SSL_DIR}/server.crt"

mkdir -p "${SSL_DIR}"

if ! command -v openssl >/dev/null 2>&1; then
  echo "[错误] 未找到 openssl，请先安装 OpenSSL"
  exit 1
fi

# 若调用方指定了非默认 CN，则临时改写 CNF 中的 CN / DNS.1
TMP_CNF="${SSL_DIR}/.openssl-san.generated.cnf"
sed "s/^CN = .*/CN = ${CN}/; s/^DNS.1 = .*/DNS.1 = ${CN}/" "${CNF}" > "${TMP_CNF}"

echo "[信息] 正在生成自签发证书..."
echo "       CN=${CN}, Days=${DAYS}"
echo "       Key=${OUT_KEY}"
echo "       Crt=${OUT_CRT}"

openssl req -x509 -nodes -newkey rsa:2048 -days "${DAYS}" \
  -keyout "${OUT_KEY}" \
  -out "${OUT_CRT}" \
  -config "${TMP_CNF}" \
  -extensions v3_req

chmod 600 "${OUT_KEY}" || true
rm -f "${TMP_CNF}"

echo "[完成] 证书已生成。请按 SSL_SETUP.md 配置 Nginx。"
openssl x509 -in "${OUT_CRT}" -noout -subject -dates