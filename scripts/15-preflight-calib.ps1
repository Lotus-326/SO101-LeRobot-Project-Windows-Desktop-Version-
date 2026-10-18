# ============================================================================
#  15 - 校准前置体检（★只读，不写任何 EEPROM★）
#
#  在跑 14-calibrate-arm.ps1 之前/之后都可以随时跑，用来回答三个问题：
#    1. 这条代码路径会不会崩？（import / draccus 解析 / 连接 / 读寄存器全走一遍）
#    2. 跑校准之前，哪几个关节需要先用手调进可编码窗口 300~3795？
#    3. 已有校准文件有没有「行程超出编码器 0~4095」「中位偏了」这类隐患？
#
#  只读保证：只用 sync_read / read，不调用任何 bus.write，
#            断开时 disable_torque=False，不会把机械臂弄软。
#
#  用法:
#    powershell -ExecutionPolicy Bypass -File scripts\15-preflight-calib.ps1
#    ... -Arm leader
# ============================================================================
[CmdletBinding()]
param(
    [ValidateSet("follower", "leader", "both")]
    [string]$Arm = "both",
    [switch]$KeepOpen
)

$ErrorActionPreference = "Stop"
. (Join-Path $PSScriptRoot "_common.ps1")
$Cfg = Import-LerobotConfig
Initialize-LerobotEnv

$argv = @(
    "$script:RootDir\_tools\preflight_calib.py", $Arm,
    "--follower-port", "$($Cfg.FollowerPort)",
    "--leader-port",   "$($Cfg.LeaderPort)",
    "--follower-id",   "$($Cfg.FollowerId)",
    "--leader-id",     "$($Cfg.LeaderId)"
)

Write-Step "校准前置体检（只读） - $Arm"
Write-Host "  从臂 Follower【白色】 @ $($Cfg.FollowerPort)  id=$($Cfg.FollowerId)"
Write-Host "  主臂 Leader【黑色】   @ $($Cfg.LeaderPort)  id=$($Cfg.LeaderId)"
Write-Host ""
Write-Host "  本脚本【不会】写任何舵机寄存器，也不会改变力矩状态。" -ForegroundColor Green
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
