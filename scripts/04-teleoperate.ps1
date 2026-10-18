# ============================================================================
#  04 - 遥操作（Leader 带动 Follower）
#
#  用法:
#    powershell -ExecutionPolicy Bypass -File scripts\04-teleoperate.ps1
#    powershell -ExecutionPolicy Bypass -File scripts\04-teleoperate.ps1 -NoCamera
#    powershell -ExecutionPolicy Bypass -File scripts\04-teleoperate.ps1 -Seconds 20
#
#  Ctrl+C 退出。
# ============================================================================
[CmdletBinding()]
param(
    [int]$Seconds = 0,      # >0 时到点自动退出
    [switch]$NoCamera       # 不接相机，只验证主从链路
)

$ErrorActionPreference = "Stop"
. (Join-Path $PSScriptRoot "_common.ps1")
$Cfg = Import-LerobotConfig
Initialize-LerobotEnv
Show-SafetyNotice
Test-PortsConfigured | Out-Null

$argv = @(
    "--robot.type=so101_follower",
    "--robot.port=$($Cfg.FollowerPort)",
    "--robot.id=$($Cfg.FollowerId)",
    "--teleop.type=so101_leader",
    "--teleop.port=$($Cfg.LeaderPort)",
    "--teleop.id=$($Cfg.LeaderId)"
)

if (-not $NoCamera) {
    $argv += Get-CameraArg
    if ($Cfg.DisplayData) { $argv += "--display_data=true" }
}

Write-Host ">>> 遥操作：Leader $($Cfg.LeaderPort) -> Follower $($Cfg.FollowerPort)" -ForegroundColor Cyan

if ($Seconds -gt 0) {
    Write-Host "（$Seconds 秒后自动停止）" -ForegroundColor Yellow
    $argLine = ConvertTo-ArgLine $argv
    $p = Start-Process -FilePath "lerobot-teleoperate" -ArgumentList $argLine -NoNewWindow -PassThru
    Start-Sleep -Seconds $Seconds
    if (-not $p.HasExited) { Stop-Process -Id $p.Id -Force }
    Write-Ok "已停止"
} else {
    Invoke-Lerobot "lerobot-teleoperate" $argv
}
