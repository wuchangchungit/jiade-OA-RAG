# =============================================================================
# 生成 Nginx 自签发 SSL 证书（Windows PowerShell）
# 用法：
#   .\gen_self_signed_cert.ps1
#   .\gen_self_signed_cert.ps1 -CommonName "rag.local" -Days 825
# =============================================================================

[CmdletBinding()]
param(
    [string]$CommonName = "localhost",
    [int]$Days = 825
)

$ErrorActionPreference = "Stop"

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$SslDir = Join-Path (Split-Path -Parent $ScriptDir) "ssl"
$CnfTemplate = Join-Path $SslDir "openssl-san.cnf"
$OutKey = Join-Path $SslDir "server.key"
$OutCrt = Join-Path $SslDir "server.crt"
$TmpCnf = Join-Path $SslDir ".openssl-san.generated.cnf"

if (-not (Test-Path $SslDir)) {
    New-Item -ItemType Directory -Force -Path $SslDir | Out-Null
}

$openssl = Get-Command openssl -ErrorAction SilentlyContinue
if (-not $openssl) {
    Write-Error "未找到 openssl。请安装 Git for Windows（含 openssl）或 Win64 OpenSSL，并确保 openssl 在 PATH 中。"
}

# 基于模板改写 CN / DNS.1
$cnfText = Get-Content -Path $CnfTemplate -Raw -Encoding UTF8
$cnfText = [regex]::Replace($cnfText, '(?m)^CN = .*$', "CN = $CommonName")
$cnfText = [regex]::Replace($cnfText, '(?m)^DNS\.1 = .*$', "DNS.1 = $CommonName")
[System.IO.File]::WriteAllText($TmpCnf, $cnfText, (New-Object System.Text.UTF8Encoding $false))

Write-Host "[信息] 正在生成自签发证书..."
Write-Host "       CN=$CommonName, Days=$Days"
Write-Host "       Key=$OutKey"
Write-Host "       Crt=$OutCrt"

& openssl req -x509 -nodes -newkey rsa:2048 -days $Days `
  -keyout $OutKey `
  -out $OutCrt `
  -config $TmpCnf `
  -extensions v3_req

Remove-Item -Force $TmpCnf -ErrorAction SilentlyContinue

Write-Host "[完成] 证书已生成。请按 SSL_SETUP.md 配置 Nginx。"
& openssl x509 -in $OutCrt -noout -subject -dates