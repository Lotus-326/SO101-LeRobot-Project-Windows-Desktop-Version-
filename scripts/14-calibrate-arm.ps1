# ============================================================================
#  14 - 整臂校准（稳版，推荐）
#
#  与官方 lerobot-calibrate 等价，但行程记录阶段【不需要按回车】：
#    - 固定时长自动窗口 + 实时「达标」提示  -> 消除"过早按回车导致 min==max"的失败模式
#    - 保存前校验每个关节行程，不足会明确报告
#    - wrist_roll 自动设为全行程 0~4095
#    - 产出 JSON 与官方完全同构，后续 teleoperate / record 直接可用
#
#  用法:
#    powershell -ExecutionPolicy Bypass -File scripts\14-calibrate-arm.ps1 -Arm follower
#    ... -Arm leader -Seconds 240
# ============================================================================
[CmdletBinding()]
param(
    [Parameter(Mandatory=$true)]
    [ValidateSet("follower", "leader")]
    [string]$Arm,
    [int]$Seconds = 240,
    [switch]$KeepOpen
)

$ErrorActionPreference = "Stop"
. (Join-Path $PSScriptRoot "_common.ps1")
$Cfg = Import-LerobotConfig
Initialize-LerobotEnv
Show-SafetyNotice

$argv = @("$script:RootDir\_tools\calibrate_arm.py", $Arm, "--seconds", "$Seconds")

Write-Step "整臂校准（稳版） - $Arm"
if ($Arm -eq "leader") {
    $port = $Cfg.LeaderPort
    $rid  = $Cfg.LeaderId
    Write-Host "  机械臂 : 主臂 Leader【黑色】 @ $port"
} else {
    $port = $Cfg.FollowerPort
    $rid  = $Cfg.FollowerId
    Write-Host "  机械臂 : 从臂 Follower【白色】 @ $port"
}
# 串口/ID 一律从 config.ps1 来，避免脚本内默认值与配置漂移
$argv += @("--port", "$port", "--id", "$rid")
Write-Host "  ID     : $rid"
Write-Host ""
Write-Host "  流程：" -ForegroundColor Cyan
Write-Host "    第0步  脚本先把 Homing_Offset 归零，并检查 6 个关节的原始读数"
Write-Host "           落在 300~3795 内（否则算不出合法 Homing_Offset）。"
Write-Host "           不适用的关节会实时提示你用手转到窗口中 —— 不用按键。"
Write-Host "    第1步  把机械臂摆到各关节活动范围【中间】的姿势，托住，按回车"
Write-Host "           中位参考图：cal_L1~L6 / cal_F1~F6（见 docs\02-整臂校准.md）"
Write-Host "    第2步  依次把每个关节缓慢推满全程（来回 2~3 遍），不用按键"
Write-Host "           界面会实时显示每个关节的行程和「达标」状态"
Write-Host "           全部达标后自动多录几秒并保存"
Write-Host ""
Write-Host "  wrist_roll（第5关节，连续旋转）会被自动设为全行程，不用特意推。" -ForegroundColor Yellow
Write-Host "  本轮的完整输出会同时写进 logs\calibrate-$Arm-<时间戳>.log" -ForegroundColor DarkGray
Write-Host ""

Push-Location $script:RepoDir
try {
    $prev = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    try { & $script:VenvPy @argv } finally { $ErrorActionPreference = $prev }
}
finally { Pop-Location }

if ($KeepOpen) {
    Write-Host "`n按回车键关闭窗口..."
    $null = Read-Host
}
