# ============================================================================
#  19 - 5 个标记点取景检查（引导式逐点拍照 + 汇总判定）
#
#  采集前必须确认：方块摆在计划里的每个标记点上时，都完整在画面里、没被裁切。
#  用 17-snapshot.ps1 要敲 5 次命令还要自己比对数值；本脚本一次走完并给总结论。
#
#  用法:
#    powershell -ExecutionPolicy Bypass -File scripts\19-marker-check.ps1
#    ... -Points 5
#    ... -Spec "{ front: {type: opencv, index_or_path: 0, ...} }"   # 临时换相机
# ============================================================================
[CmdletBinding()]
param(
    [int]$Points = 5,
    [string]$Spec = ""
)

$ErrorActionPreference = "Stop"
. (Join-Path $PSScriptRoot "_common.ps1")
$Cfg = Import-LerobotConfig
Initialize-LerobotEnv

if (-not $Spec) { $Spec = $Cfg.Cameras }
if ([string]::IsNullOrWhiteSpace($Spec)) {
    Write-Bad "config.ps1 里的 Cameras 是空的 —— 先跑 scripts\05-find-cameras.ps1 拿到序列号并填进去"
    exit 1
}

Write-Step "标记点取景检查（共 $Points 个点）"
Write-Host "  相机片段: $Spec"
Write-Host ""
Write-Host "  这一步只读相机，不动机械臂。" -ForegroundColor Green
Write-Host "  每个点：把方块摆到标记上 -> 按回车拍照 -> 看判据（不合格可 r 重拍）" -ForegroundColor Cyan
Write-Host ""

$argv = @("$script:RootDir\_tools\marker_check.py", "--spec", $Spec, "--points", "$Points")

Push-Location $script:RepoDir
try {
    $prev = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    try { & $script:VenvPy @argv } finally { $ErrorActionPreference = $prev }
    $rc = $LASTEXITCODE
}
finally { Pop-Location }

exit $rc
