# ============================================================================
#  06 - 数据采集（录制数据集）
#
#  用法:
#    powershell -ExecutionPolicy Bypass -File scripts\06-record.ps1
#    powershell -ExecutionPolicy Bypass -File scripts\06-record.ps1 -NumEpisodes 10 -EpisodeTimeS 25
#    powershell -ExecutionPolicy Bypass -File scripts\06-record.ps1 -Resume     # 断点续录
#
#  录制中的键盘控制（焦点必须在运行窗口上）:
#    右箭头 -> 提前结束当前 episode / reset，进入下一阶段
#    左箭头 -> 放弃当前 episode，重录
#    ESC    -> 结束整个会话并编码视频
#
#  数据默认保存在 %USERPROFILE%\.cache\huggingface\lerobot\<repo_id>
# ============================================================================
[CmdletBinding()]
param(
    [string]$RepoId,
    [string]$Task,
    [int]$NumEpisodes,
    [double]$EpisodeTimeS,
    [double]$ResetTimeS,
    [int]$Fps = 30,
    [string]$VCodec = "",          # h264 / hevc / libsvtav1，留空用默认
    [switch]$NoVideo,              # 不编码视频（调试用，数据集会很大）
    [switch]$NoCamera,
    [switch]$PushToHub,
    [switch]$Resume,
    [switch]$NoDisplay
)

$ErrorActionPreference = "Stop"
. (Join-Path $PSScriptRoot "_common.ps1")
$Cfg = Import-LerobotConfig
Initialize-LerobotEnv
Show-SafetyNotice
Test-PortsConfigured | Out-Null

if (-not $RepoId)       { $RepoId       = $Cfg.DatasetRepoId }
if (-not $Task)         { $Task         = $Cfg.Task }
if (-not $NumEpisodes)  { $NumEpisodes  = $Cfg.NumEpisodes }
if (-not $EpisodeTimeS) { $EpisodeTimeS = $Cfg.EpisodeTimeS }
if (-not $ResetTimeS)   { $ResetTimeS   = $Cfg.ResetTimeS }

$argv = @(
    "--robot.type=so101_follower",
    "--robot.port=$($Cfg.FollowerPort)",
    "--robot.id=$($Cfg.FollowerId)",
    "--teleop.type=so101_leader",
    "--teleop.port=$($Cfg.LeaderPort)",
    "--teleop.id=$($Cfg.LeaderId)",
    "--dataset.repo_id=$RepoId",
    "--dataset.single_task=$Task",
    "--dataset.num_episodes=$NumEpisodes",
    "--dataset.episode_time_s=$EpisodeTimeS",
    "--dataset.reset_time_s=$ResetTimeS",
    "--dataset.fps=$Fps"
)

if (-not $NoCamera)  { $argv += Get-CameraArg }
if (-not $NoVideo)   { $argv += "--dataset.video=true" } else { $argv += "--dataset.video=false" }
if ($VCodec)         { $argv += "--dataset.vcodec=$VCodec" }
if ($PushToHub)      { $argv += "--dataset.push_to_hub=true" } else { $argv += "--dataset.push_to_hub=false" }
if ($Resume)         { $argv += "--resume=true" }
if ($Cfg.DisplayData -and -not $NoDisplay) { $argv += "--display_data=true" }
$argv += "--play_sounds=false"

Write-Host ">>> 开始采集：$NumEpisodes 个 episode x ${EpisodeTimeS}s（重置 ${ResetTimeS}s）" -ForegroundColor Cyan
Write-Host "    数据集: $RepoId"
Write-Host "    任务  : $Task"
Write-Host "    相机  : $($Cfg.Cameras)"
Write-Host ""
Write-Host "  +-- 录制按键（焦点必须在这个窗口上）-------------------------+" -ForegroundColor Yellow
Write-Host "  |  ->  右箭头   提前结束当前回合 / 复位，进下一阶段           |" -ForegroundColor Yellow
Write-Host "  |  <-  左箭头   丢弃当前回合并重录（抓失败了就用它）          |" -ForegroundColor Yellow
Write-Host "  |  空格        暂停 / 继续（暂停时不录新帧，主从跟随继续）   |" -ForegroundColor Yellow
Write-Host "  |  x           急停：丢弃当前条 + 结束会话 + 收尾释放力矩    |" -ForegroundColor Yellow
Write-Host "  |  ESC         结束会话（会先编码视频，别直接关窗口）        |" -ForegroundColor Yellow
Write-Host "  +-----------------------------------------------------------+" -ForegroundColor Yellow
Write-Host ""
Write-Host "  收尾三步（按 ESC 之前）：松开主臂扳机张开夹爪 -> 摆放松姿势 -> 再按 ESC" -ForegroundColor DarkGray
Write-Host "  这样可避免收尾时夹爪堵转触发的 Overload 报错。" -ForegroundColor DarkGray
Write-Host ""

Invoke-Lerobot "lerobot-record" $argv

$dsPath = Join-Path $env:USERPROFILE ".cache\huggingface\lerobot\$RepoId"
if (Test-Path $dsPath) {
    Write-Ok "数据集目录: $dsPath"
    Get-ChildItem $dsPath | Select-Object Name | Format-Table -AutoSize
} else {
    Write-Warn2 "未找到数据集目录（若指定了 --dataset.root 请到该路径查看）"
}
