# LeRobot 环境安装脚本（Windows 原生 / Windows PowerShell 5.1 兼容）
#
# 用法:
#   powershell -ExecutionPolicy Bypass -File scripts\setup-env.ps1
#   powershell -ExecutionPolicy Bypass -File scripts\setup-env.ps1 -SkipTorch
#   powershell -ExecutionPolicy Bypass -File scripts\setup-env.ps1 -UseProxy   # 直连不通时才开
#
# 说明:
#   - 在项目根目录创建 .venv 虚拟环境（基于 D:\python 的 Python 3.13）
#   - 安装 PyTorch + torchvision 的 CUDA 版
#   - 以可编辑模式安装 lerobot[feetech,orbbec]
#
# 网络策略（本机实测）:
#   清华 PyPI 镜像        —— 直连快
#   download.pytorch.org  —— 直连约 1.4 MB/s（经 Clash 代理反而会 SSL EOF/卡死）
#   mirrors.aliyun.com    —— 仅 0.3 MB/s，不采用
#   所以默认【不走代理】；需要时用 -UseProxy 打开。

[CmdletBinding()]
param(
    [string]$TorchVersion       = "2.7.1",
    [string]$TorchVisionVersion = "0.22.1",
    [string]$CudaTag            = "cu128",
    [string]$PypiMirror         = "https://pypi.tuna.tsinghua.edu.cn/simple",
    [string]$TorchIndex         = "https://download.pytorch.org/whl",
    [string]$TorchFallback      = "https://mirror.sjtu.edu.cn/pytorch-wheels",
    [string]$Proxy              = "http://127.0.0.1:7897",
    [switch]$SkipTorch,
    [switch]$UseProxy
)

$ErrorActionPreference = "Stop"
try { [Console]::OutputEncoding = [System.Text.Encoding]::UTF8 } catch {}

$Root = Split-Path -Parent $PSScriptRoot
$Venv = Join-Path $Root ".venv"
$Py   = Join-Path $Venv "Scripts\python.exe"
$Repo = Join-Path $Root "lerobot"

Write-Host "== LeRobot 环境安装 ==" -ForegroundColor Cyan
Write-Host "项目根目录: $Root"

if (-not (Test-Path $Py)) {
    Write-Host "-> 创建虚拟环境 $Venv" -ForegroundColor Yellow
    python -m venv $Venv
}

# ---- 网络：默认直连；-UseProxy 时开代理但让国内镜像绕过 ----
if ($UseProxy) {
    $env:HTTP_PROXY  = $Proxy
    $env:HTTPS_PROXY = $Proxy
    $env:NO_PROXY    = "localhost,127.0.0.1,::1,pypi.tuna.tsinghua.edu.cn,mirror.sjtu.edu.cn,mirrors.aliyun.com"
    Write-Host "-> 已启用代理 $Proxy（国内镜像走 NO_PROXY）" -ForegroundColor Yellow
} else {
    $env:HTTP_PROXY  = ""
    $env:HTTPS_PROXY = ""
    $env:NO_PROXY    = "*"
    Write-Host "-> 直连模式（不使用代理）"
}

# 坑：PowerShell 5.1 会直接丢掉空字符串参数，所以不能写 `--proxy ""`
#     （会被解析成 --proxy <下一个参数>，pip 报 "You must give at least one requirement"）。
#     这里统一用 HTTP_PROXY / HTTPS_PROXY / NO_PROXY 环境变量控制代理。
$pipCommon = @("-m", "pip", "install", "--retries", "10", "--timeout", "180")

& $Py @pipCommon -U pip setuptools wheel --index-url $PypiMirror
if ($LASTEXITCODE -ne 0) { throw "pip 自更新失败" }

if (-not $SkipTorch) {
    Write-Host "-> 安装 PyTorch $TorchVersion+$CudaTag / torchvision $TorchVisionVersion+$CudaTag" -ForegroundColor Yellow
    $ok = $false

    Write-Host "   [1/2] 官方源 $TorchIndex/$CudaTag  (约 3.3 GB，1~2 MB/s，请耐心等待)"
    & $Py @pipCommon "torch==$TorchVersion" "torchvision==$TorchVisionVersion" `
        --index-url "$TorchIndex/$CudaTag" `
        --extra-index-url $PypiMirror
    if ($LASTEXITCODE -eq 0) { $ok = $true }

    if (-not $ok) {
        Write-Host "   [2/2] 回退上海交大镜像 $TorchFallback/$CudaTag" -ForegroundColor Yellow
        & $Py @pipCommon "torch==$TorchVersion" "torchvision==$TorchVisionVersion" `
            --index-url $PypiMirror `
            --find-links "$TorchFallback/$CudaTag/"
        if ($LASTEXITCODE -ne 0) { throw "PyTorch 安装失败（可尝试 -UseProxy）" }
    }
}

Write-Host "-> 安装 lerobot[feetech,orbbec]（可编辑模式）..." -ForegroundColor Yellow
Push-Location $Repo
try {
    & $Py @pipCommon -e ".[feetech,orbbec]" --index-url $PypiMirror
    if ($LASTEXITCODE -ne 0) { throw "lerobot 安装失败" }
}
finally {
    Pop-Location
}

Write-Host "-> 校验 ..." -ForegroundColor Yellow
& $Py -c "import torch, torchvision; print('torch       ', torch.__version__, '| cuda:', torch.cuda.is_available())"
& $Py -c "import av; print('av          ', av.__version__, '| libsvtav1:', 'libsvtav1' in av.codecs_available)"
& $Py -c "import lerobot; print('lerobot     ', lerobot.__file__)"

Write-Host "== 完成 ==" -ForegroundColor Green
