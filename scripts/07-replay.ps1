# ============================================================================
#  07 - 回放数据集（在真机上复现某个 episode 的动作）
#
#  用法:
#    powershell -ExecutionPolicy Bypass -File scripts\07-replay.ps1 -Episode 0
#    powershell -ExecutionPolicy Bypass -File scripts\07-replay.ps1 -Episode 3 -RepoId seeedstudio123/m1_pick_cube
# ============================================================================
[CmdletBinding()]
param(
    [int]$Episode = 0,
    [string]$RepoId,
    [string]$Root
)

$ErrorActionPreference = "Stop"
. (Join-Path $PSScriptRoot "_common.ps1")
$Cfg = Import-LerobotConfig
Initialize-LerobotEnv
Show-SafetyNotice

if (-not $RepoId) { $RepoId = $Cfg.DatasetRepoId }
if (-not $Root)   { $Root = Join-Path $env:USERPROFILE ".cache\huggingface\lerobot\$RepoId" }

$argv = @(
    "--robot.type=so101_follower",
    "--robot.port=$($Cfg.FollowerPort)",
    "--robot.id=$($Cfg.FollowerId)",
    "--dataset.repo_id=$RepoId",
    "--dataset.episode=$Episode"
)
if (Test-Path $Root) { $argv += "--dataset.root=$Root" }

Write-Host ">>> 回放 $RepoId 第 $Episode 个 episode" -ForegroundColor Cyan
Invoke-Lerobot "lerobot-replay" $argv
