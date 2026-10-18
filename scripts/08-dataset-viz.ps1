# ============================================================================
#  08 - 数据集可视化（rerun 本地查看器）
#
#  用法:
#    powershell -ExecutionPolicy Bypass -File scripts\08-dataset-viz.ps1 -EpisodeIndex 0
#    powershell -ExecutionPolicy Bypass -File scripts\08-dataset-viz.ps1 -EpisodeIndex 0 -Save
#
#  -Save 时不弹窗，改为导出 .rrd 文件到 outputs\rrd\，之后可用 `rerun xxx.rrd` 打开。
# ============================================================================
[CmdletBinding()]
param(
    [Parameter(Mandatory=$true)][int]$EpisodeIndex,
    [string]$RepoId,
    [string]$Root,
    [switch]$Save,
    [switch]$DisplayCompressedImages
)

$ErrorActionPreference = "Stop"
. (Join-Path $PSScriptRoot "_common.ps1")
$Cfg = Import-LerobotConfig
Initialize-LerobotEnv

if (-not $RepoId) { $RepoId = $Cfg.DatasetRepoId }
if (-not $Root)   { $Root = Join-Path $env:USERPROFILE ".cache\huggingface\lerobot\$RepoId" }

$argv = @(
    "--repo-id=$RepoId",
    "--episode-index=$EpisodeIndex",
    "--root=$Root",
    "--mode=local"
)
if ($DisplayCompressedImages) { $argv += "--display-compressed-images=true" } else { $argv += "--display-compressed-images=false" }
if ($Save) {
    $outDir = Join-Path $script:RepoDir "outputs\rrd"
    New-Item -ItemType Directory -Force -Path $outDir | Out-Null
    $argv += "--save=1"
    $argv += "--output-dir=$outDir"
    Write-Host ">>> 导出 .rrd 到 $outDir" -ForegroundColor Cyan
} else {
    Write-Host ">>> 启动 rerun 查看器（关掉窗口即退出）" -ForegroundColor Cyan
}

Invoke-Lerobot "lerobot-dataset-viz" $argv
