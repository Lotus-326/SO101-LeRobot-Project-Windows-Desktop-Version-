# ============================================================================
#  20 - 把校准文件写回舵机（修复「舵机内校准与文件不一致」）
#
#  什么时候需要：
#    `18-gonogo.ps1` 第 3 项报「舵机↔文件不一致」时。
#    典型原因是一次中途被打断的校准：set_half_turn_homings() 已经改了
#    Homing_Offset，但行程还没写回，于是舵机状态与校准文件对不上。
#
#    不修的话，录制第一秒会对两臂各弹一次
#      Press ENTER to use provided calibration file ..., or type 'c' ...
#    按回车 = 执行本脚本做的事；按成 'c' 会重新校准、覆盖掉已验证好的校准。
#
#  安全性：写 Homing_Offset 前会强制失能力矩；写完后机械臂是软的，请托住。
#          只写校准寄存器，不动 ID / 波特率 / PID。
#
#  用法:
#    powershell -ExecutionPolicy Bypass -File scripts\20-sync-calib.ps1
#    powershell -ExecutionPolicy Bypass -File scripts\20-sync-calib.ps1 -Arm leader
#    powershell -ExecutionPolicy Bypass -File scripts\20-sync-calib.ps1 -Check   # 只对比
# ============================================================================
[CmdletBinding()]
param(
    [ValidateSet("follower", "leader", "both")]
    [string]$Arm = "both",
    [switch]$Check
)

$ErrorActionPreference = "Stop"
. (Join-Path $PSScriptRoot "_common.ps1")
$Cfg = Import-LerobotConfig
Initialize-LerobotEnv

$argv = @(
    "$script:RootDir\_tools\sync_calibration.py", $Arm,
    "--follower-port", "$($Cfg.FollowerPort)",
    "--leader-port",   "$($Cfg.LeaderPort)",
    "--follower-id",   "$($Cfg.FollowerId)",
    "--leader-id",     "$($Cfg.LeaderId)"
)
if ($Check) { $argv += "--check" }

Write-Step "校准文件 -> 舵机 EEPROM 同步 - $Arm"
if ($Check) {
    Write-Host "  模式: 只对比，不写入" -ForegroundColor Green
} else {
    Write-Host "  模式: 写入（会先失能力矩，机械臂会变软，请托住）" -ForegroundColor Yellow
}
Write-Host ""

Push-Location $script:RepoDir
try {
    $prev = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    try { & $script:VenvPy @argv } finally { $ErrorActionPreference = $prev }
    $rc = $LASTEXITCODE
}
finally { Pop-Location }

exit $rc
