# ============================================================================
#  03 - 整臂校准（Leader / Follower）
#
#  用法:
#    powershell -ExecutionPolicy Bypass -File scripts\03-calibrate.ps1 -Arm follower
#    powershell -ExecutionPolicy Bypass -File scripts\03-calibrate.ps1 -Arm leader -Recalibrate
#
#  校准流程（终端会提示）:
#    1. 先把机械臂摆到各关节「活动范围中间」的姿势（参考 Wiki 校准图）
#    2. 回车
#    3. 依次把每个关节从头到尾缓慢移动一遍完整行程
#    4. 校准文件保存到 %USERPROFILE%\.cache\huggingface\lerobot\calibration\
#
#  -Recalibrate: 先删除对应的旧校准文件再校准
# ============================================================================
[CmdletBinding()]
param(
    [Parameter(Mandatory=$true)]
    [ValidateSet("follower", "leader")]
    [string]$Arm,
    [string]$Port,
    [string]$Id,
    [switch]$Recalibrate
)

$ErrorActionPreference = "Stop"
. (Join-Path $PSScriptRoot "_common.ps1")
$Cfg = Import-LerobotConfig
Initialize-LerobotEnv
Show-SafetyNotice

$calibRoot = Join-Path $env:USERPROFILE ".cache\huggingface\lerobot\calibration"

if ($Arm -eq "follower") {
    if (-not $Port) { $Port = $Cfg.FollowerPort }
    if (-not $Id)   { $Id   = $Cfg.FollowerId }
    $sub    = "robots\so_follower"          # 注意：robot 的 name 是 so_follower，会多一层子目录
    $argv   = @("--robot.type=so101_follower", "--robot.port=$Port", "--robot.id=$Id")
    $label  = "从动臂 Follower"
} else {
    if (-not $Port) { $Port = $Cfg.LeaderPort }
    if (-not $Id)   { $Id   = $Cfg.LeaderId }
    $sub    = "teleoperators\so_leader"     # 同理，teleoperator 的 name 是 so_leader
    $argv   = @("--teleop.type=so101_leader", "--teleop.port=$Port", "--teleop.id=$Id")
    $label  = "领导臂 Leader"
}

Write-Host ">>> 校准【$label】 端口=$Port  ID=$Id" -ForegroundColor Cyan

$calibFile = Join-Path $calibRoot "$sub\$Id.json"
if ($Recalibrate -and (Test-Path $calibFile)) {
    Remove-Item $calibFile -Force
    Write-Warn2 "已删除旧校准文件 $calibFile"
}
if (Test-Path $calibFile) {
    Write-Warn2 "已存在校准文件：$calibFile"
    Write-Warn2 "终端会询问：直接回车=沿用旧校准；输入 c 回车=重新校准"
}

Invoke-Lerobot "lerobot-calibrate" $argv

if (Test-Path $calibFile) { Write-Ok "校准文件已生成: $calibFile" } else { Write-Warn2 "未发现校准文件，请确认校准是否成功完成" }
