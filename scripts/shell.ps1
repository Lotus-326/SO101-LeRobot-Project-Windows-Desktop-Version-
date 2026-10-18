# ============================================================================
#  shell - 进入已激活本项目环境的交互式终端
#  用法: powershell -ExecutionPolicy Bypass -File scripts\shell.ps1
#  进入后可直接运行 lerobot-* 命令，例如:
#     lerobot-info
#     lerobot-teleoperate --robot.type=so101_follower --robot.port=COM4 ...
# ============================================================================
[CmdletBinding()]
param()

$ErrorActionPreference = "Stop"
. (Join-Path $PSScriptRoot "_common.ps1")
$Cfg = Import-LerobotConfig
Initialize-LerobotEnv

Set-Location $script:RepoDir
Write-Host "LeRobot 环境已激活 (仓库目录: $script:RepoDir)" -ForegroundColor Green
Write-Host "ffmpeg: $script:FfmpegBin"
Write-Host "退出请输入 exit`n" -ForegroundColor Yellow

& powershell -NoExit -Command "Set-Location '$script:RepoDir'"
