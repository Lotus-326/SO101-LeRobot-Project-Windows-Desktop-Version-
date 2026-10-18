# ============================================================================
#  17 - 抓一张相机样张（确认取景，不碰机械臂）
#
#  采集前最值得做的一件事：把物体摆到计划里的每个位置、各拍一张，
#  确认它们都在画面内、没被裁切、也足够大。
#
#  用法:
#    powershell -ExecutionPolicy Bypass -File scripts\17-snapshot.ps1
#    ... -Label pos1              # 存成 front_pos1.png，便于逐个位置对比
#    ... -Open                    # 存完自动用默认看图程序打开
# ============================================================================
[CmdletBinding()]
param(
    [string]$Label = "now",
    [string]$Out = "",
    [int]$Frames = 5,
    [switch]$Open
)

$ErrorActionPreference = "Stop"
. (Join-Path $PSScriptRoot "_common.ps1")
$Cfg = Import-LerobotConfig
Initialize-LerobotEnv

if ([string]::IsNullOrWhiteSpace($Cfg.Cameras)) {
    Write-Bad "config.ps1 里的 Cameras 是空的 —— 先跑 scripts\05-find-cameras.ps1 拿到序列号并填进去"
    exit 1
}

$argv = @("$script:RootDir\_tools\snapshot.py", "--spec", $Cfg.Cameras,
          "--label", $Label, "--frames", "$Frames")
if ($Out) { $argv += @("--out", $Out) }

Write-Step "抓样张（只读相机，不动机械臂）"
Write-Host "  相机片段: $($Cfg.Cameras)"
Write-Host ""

Push-Location $script:RepoDir
try {
    $prev = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    try { & $script:VenvPy @argv } finally { $ErrorActionPreference = $prev }
    $rc = $LASTEXITCODE
}
finally { Pop-Location }

$shot = if ($Out) { $Out } else { Join-Path $script:RepoDir "outputs\captured_images\front_$Label.png" }
if ((Test-Path $shot) -and $Open) { Start-Process $shot }

if ($rc -ne 0) { exit $rc }
