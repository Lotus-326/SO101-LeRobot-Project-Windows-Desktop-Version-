# ============================================================================
#  16 - SoARM 中位校准（安全版，等价于 Seeed 工具的「串口中位校准」）
#
#  对应官方 Wiki：https://wiki.seeedstudio.com/cn/lerobot_steering_gear_debugging_tool/
#  对应工具源码：tools\Seeed_RoboController\src\tools\servo_quick_calibration.py
#
#  同样给每个舵机写「寄存器40 = 128」= 把【当前位置】记为中位 2048，
#  但把顺序改成「失能 -> 你摆好姿势 -> 按回车确认 -> 立刻写」，
#  消除 Seeed 原版「失能后 sleep(1) 再写」中间那段松手就会垮下去、
#  中位被记歪的窗口（docs\11-舵机调试工具.md 里有那次事故记录）。
#
#  用法:
#    # 只读体检：显示位置 / Homing_Offset / 力矩，不写任何寄存器
#    powershell -ExecutionPolicy Bypass -File scripts\16-middle-calibrate.ps1 -Arm follower -DryRun
#
#    # 正式写入中位（会提示你摆姿势、按回车确认）
#    powershell -ExecutionPolicy Bypass -File scripts\16-middle-calibrate.ps1 -Arm follower
#    powershell -ExecutionPolicy Bypass -File scripts\16-middle-calibrate.ps1 -Arm leader
# ============================================================================
[CmdletBinding()]
param(
    [Parameter(Mandatory=$true)]
    [ValidateSet("follower", "leader")]
    [string]$Arm,
    [string]$Port = "",
    [switch]$DryRun,
    [switch]$KeepOpen
)

$ErrorActionPreference = "Stop"
. (Join-Path $PSScriptRoot "_common.ps1")
$Cfg = Import-LerobotConfig
Initialize-LerobotEnv
Show-SafetyNotice

if (-not $Port) {
    $Port = if ($Arm -eq "leader") { $Cfg.LeaderPort } else { $Cfg.FollowerPort }
}

$argv = @("$script:RootDir\_tools\soarm_middle_calibrate.py", $Arm, "--port", "$Port")
if ($DryRun) { $argv += "--dry-run" }

Write-Step "SoARM 中位校准（安全版） - $Arm"
if ($Arm -eq "leader") {
    Write-Host "  机械臂 : 主臂 Leader【黑色】 @ $Port"
    Write-Host "  参考图 : cal_L1 ~ cal_L6"
} else {
    Write-Host "  机械臂 : 从臂 Follower【白色】 @ $Port"
    Write-Host "  参考图 : cal_F1 ~ cal_F6"
}
if ($DryRun) {
    Write-Host "  模式   : 只读 dry-run（不写任何寄存器）" -ForegroundColor Green
} else {
    Write-Host "  模式   : 写入中位" -ForegroundColor Yellow
}
Write-Host ""
Write-Host "  流程：" -ForegroundColor Cyan
Write-Host "    1. 扫描舵机、打印当前 位置 / Homing_Offset / 力矩"
Write-Host "    2. 失能所有舵机 —— 机械臂会变软，请先托住"
Write-Host "    3. 把机械臂摆到官方中位姿势，托住不动，按回车"
Write-Host "    4. 再确认一次（输入 y），然后写入中位"
Write-Host ""
Write-Host "  ⚠ 这一步只对齐「中位/零点」，【不会】修正遥操作幅度。" -ForegroundColor Yellow
Write-Host "    写完后仍需跑 14-calibrate-arm.ps1，并把行程推到顶住限位。" -ForegroundColor Yellow
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
