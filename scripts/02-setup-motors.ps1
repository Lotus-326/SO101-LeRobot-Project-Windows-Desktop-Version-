# ============================================================================
#  02 - 舵机 ID / 波特率配置（散件组装时用；已组装好的整臂可以跳过）
#
#  用法:
#    powershell -ExecutionPolicy Bypass -File scripts\02-setup-motors.ps1 -Arm follower
#    powershell -ExecutionPolicy Bypass -File scripts\02-setup-motors.ps1 -Arm leader
#    powershell -ExecutionPolicy Bypass -File scripts\02-setup-motors.ps1 -Arm leader -Port COM7
#
#  说明:
#    脚本会依次提示：只把「当前这一个」舵机接到驱动板 -> 回车。
#    舵机顺序（从底座往上）: shoulder_pan, shoulder_lift, elbow_flex,
#                            wrist_flex, wrist_roll, gripper
#    每次回车前请确认：电脑 -> USB -> 驱动板 -> 三针线 -> 该舵机（不串接其它舵机）
# ============================================================================
[CmdletBinding()]
param(
    [Parameter(Mandatory=$true)]
    [ValidateSet("follower", "leader")]
    [string]$Arm,
    [string]$Port
)

$ErrorActionPreference = "Stop"
. (Join-Path $PSScriptRoot "_common.ps1")
$Cfg = Import-LerobotConfig
Initialize-LerobotEnv
Show-SafetyNotice

if ($Arm -eq "follower") {
    if (-not $Port) { $Port = $Cfg.FollowerPort }
    $argv = @("--robot.type=so101_follower", "--robot.port=$Port")
    Write-Host ">>> 配置【从动臂 Follower】舵机, 端口 $Port" -ForegroundColor Cyan
} else {
    if (-not $Port) { $Port = $Cfg.LeaderPort }
    $argv = @("--teleop.type=so101_leader", "--teleop.port=$Port")
    Write-Host ">>> 配置【领导臂 Leader】舵机, 端口 $Port" -ForegroundColor Cyan
}

Write-Host "注意：Leader 使用 7.4V(5V 供电) 舵机，Follower 标准版 5V / Pro 版 12V。" -ForegroundColor Yellow
Write-Host "     电压接错会烧舵机！`n"

Invoke-Lerobot "lerobot-setup-motors" $argv
