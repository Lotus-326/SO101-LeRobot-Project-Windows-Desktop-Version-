# ============================================================================
#  18 - 正式采集前 GO / NO-GO 自检
#
#  一条命令回答「现在能不能开录」。检查 7 项：
#    1. 串口在不在、是不是 USB 转串口
#    2. 两臂校准文件在不在
#    3. 舵机内校准 与 校准文件 是否一致
#    4. 主从臂行程幅度是否对齐（遥操作准不准）
#    5. 相机能不能开、物块在不在画面里、有没有被裁切
#    6. 磁盘剩余空间
#    7. 目标数据集是否已存在（已存在要 -Resume 或先清理）
#
#  全部通过打印 GO；否则打印 NO-GO 和具体原因，退出码 1。
#
#  用法:
#    powershell -ExecutionPolicy Bypass -File scripts\18-gonogo.ps1
#    ... -NumEpisodes 50 -EpisodeTimeS 15
# ============================================================================
[CmdletBinding()]
param(
    [string]$RepoId = "",
    [int]$NumEpisodes = 0,
    [double]$EpisodeTimeS = 0
)

$ErrorActionPreference = "Stop"
. (Join-Path $PSScriptRoot "_common.ps1")
$Cfg = Import-LerobotConfig
Initialize-LerobotEnv

if (-not $RepoId)       { $RepoId       = $Cfg.DatasetRepoId }
if (-not $NumEpisodes)  { $NumEpisodes  = $Cfg.NumEpisodes }
if (-not $EpisodeTimeS) { $EpisodeTimeS = $Cfg.EpisodeTimeS }

$argv = @(
    "$script:RootDir\_tools\gonogo.py",
    "--follower-port", "$($Cfg.FollowerPort)",
    "--leader-port",   "$($Cfg.LeaderPort)",
    "--follower-id",   "$($Cfg.FollowerId)",
    "--leader-id",     "$($Cfg.LeaderId)",
    "--repo-id",       "$RepoId",
    "--num-episodes",  "$NumEpisodes",
    "--episode-time-s", "$EpisodeTimeS"
)
if (-not [string]::IsNullOrWhiteSpace($Cfg.Cameras)) {
    $argv += @("--spec", $Cfg.Cameras)
}

Push-Location $script:RepoDir
try {
    $prev = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    try { & $script:VenvPy @argv } finally { $ErrorActionPreference = $prev }
    $rc = $LASTEXITCODE
}
finally { Pop-Location }

exit $rc
