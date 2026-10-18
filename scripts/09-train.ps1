# ============================================================================
#  09 - 训练策略（默认 ACT）
#
#  用法:
#    powershell -ExecutionPolicy Bypass -File scripts\09-train.ps1
#    powershell -ExecutionPolicy Bypass -File scripts\09-train.ps1 -Steps 100000 -BatchSize 16
#    powershell -ExecutionPolicy Bypass -File scripts\09-train.ps1 -Resume
#
#  产物: <OutputDir>\checkpoints\last\pretrained_model
#
#  显存不足（RTX 4060 8GB）时的处理:
#    - 降低 -BatchSize（8 -> 4）
#    - 降低 --dataset.fps 或相机分辨率（需重新采集）
# ============================================================================
[CmdletBinding()]
param(
    [string]$RepoId,
    [ValidateSet("act", "diffusion", "vqbet", "tdmpc", "smolvla")]
    [string]$PolicyType,
    [int]$Steps,
    [int]$BatchSize,
    [string]$OutputDir,
    [string]$JobName,
    [string]$Device = "cuda",
    [int]$NumWorkers = 4,
    [switch]$Resume,
    [switch]$Wandb,
    [switch]$PushToHub,
    [string]$PolicyPath            # 微调预训练模型时使用，如 lerobot/smolvla_base
)

$ErrorActionPreference = "Stop"
. (Join-Path $PSScriptRoot "_common.ps1")
$Cfg = Import-LerobotConfig
Initialize-LerobotEnv

if (-not $RepoId)     { $RepoId     = $Cfg.DatasetRepoId }
if (-not $PolicyType) { $PolicyType = $Cfg.PolicyType }
if (-not $Steps)      { $Steps      = $Cfg.TrainSteps }
if (-not $BatchSize)  { $BatchSize  = $Cfg.BatchSize }
if (-not $OutputDir)  { $OutputDir  = $Cfg.OutputDir }
if (-not $JobName)    { $JobName    = $Cfg.JobName }

$repoRoot = $script:RepoDir
$absOut   = if ([System.IO.Path]::IsPathRooted($OutputDir)) { $OutputDir } else { Join-Path $repoRoot $OutputDir }

# ⚠️ 这里【绝对不要】提前 New-Item 建目录！
#    lerobot-train 的 validate()（configs/train.py:119）规定：
#      「output_dir 已存在 且 resume=False」→ 直接抛 FileExistsError。
#    输出目录由 train_utils.py 的 save_checkpoint() 自己 mkdir(parents=True)。
#    （历史 bug：脚本先建了空目录，导致 5 千步短跑一启动就报 FileExistsError）
if (-not $Resume -and (Test-Path $absOut)) {
    $hasContent = (Get-ChildItem $absOut -Force -ErrorAction SilentlyContinue | Measure-Object).Count -gt 0
    if ($hasContent) {
        Write-Bad "输出目录已存在且非空：$absOut"
        Write-Host "  LeRobot 拒绝覆盖已有训练目录。三选一：" -ForegroundColor Yellow
        Write-Host "    1) 续训      : 加 -Resume"
        Write-Host "    2) 换目录    : 加 -OutputDir outputs/train/act_xxx_v2"
        Write-Host "    3) 删掉重训  : Remove-Item -Recurse -Force `"$absOut`""
        throw "输出目录冲突，未开始训练"
    }
    # 空的残留目录：删掉，让 lerobot-train 自己重建
    Remove-Item -Force $absOut -ErrorAction SilentlyContinue
    Write-Host "  （已清理空的残留输出目录）" -ForegroundColor DarkGray
}

if ($Resume) {
    $cfgJson = Join-Path $absOut "checkpoints\last\pretrained_model\train_config.json"
    if (-not (Test-Path $cfgJson)) { throw "找不到 $cfgJson，无法续训" }
    $argv = @("--config_path=$cfgJson", "--resume=true")
    Write-Host ">>> 从检查点续训: $cfgJson" -ForegroundColor Cyan
} else {
    $argv = @(
        "--dataset.repo_id=$RepoId",
        "--policy.type=$PolicyType",
        "--output_dir=$absOut",
        "--job_name=$JobName",
        "--policy.device=$Device",
        "--steps=$Steps",
        "--batch_size=$BatchSize",
        "--num_workers=$NumWorkers",
        "--save_freq=$($Cfg.SaveFreq)",
        "--log_freq=$($Cfg.LogFreq)"
    )
    if ($PolicyPath) { $argv += "--policy.path=$PolicyPath" }
    if ($Wandb) { $argv += "--wandb.enable=true" } else { $argv += "--wandb.enable=false" }
    if ($PushToHub) { $argv += "--policy.push_to_hub=true" } else { $argv += "--policy.push_to_hub=false" }
    Write-Host ">>> 开始训练: $PolicyType  数据集=$RepoId  steps=$Steps  batch=$BatchSize" -ForegroundColor Cyan
}

Write-Host "    输出目录: $absOut"
Write-Host "    训练期间显存/日志会在终端滚动输出，按 Ctrl+C 可中断（检查点已保存）`n" -ForegroundColor Yellow

# ----------------------------------------------------------------------------
# 压制 torchvision 的视频 IO 弃用告警刷屏。
#
# 现象：训练一开始会反复打印
#   UserWarning: The video decoding and encoding capabilities of torchvision are
#   deprecated from version 0.22 ...
# 原因：每个 DataLoader worker 首次解码视频时各打一次，每个 epoch 重建 worker 又刷一遍。
# 但本项目解码视频走 PyAV（启动日志 "torchcodec is not available ... falling back
# to pyav"），根本不经过 torchvision 的视频 IO —— 这条告警毫无信息价值，
# 却会淹没真正的 loss / grdn 日志。
#
# ⚠️ 实测：按消息内容过滤【无效】—— 下面两种写法都压不掉：
#      ignore:.*video decoding.*:UserWarning
#      ignore:The video decoding and encoding...:UserWarning
#    Python 的 -W 对 message 字段的实际匹配行为与文档描述不符。
#    只有按 category 过滤才生效：ignore::UserWarning
#    安全性：真正重要的 "torchcodec not available" 那句是 logging.warning，
#    不经过 warnings 模块，因此不会被这个过滤器波及。
# ----------------------------------------------------------------------------
$env:PYTHONWARNINGS = if ($env:PYTHONWARNINGS) { "$($env:PYTHONWARNINGS),ignore::UserWarning" } else { "ignore::UserWarning" }

Push-Location $repoRoot
try {
    Invoke-Lerobot "lerobot-train" $argv
}
finally { Pop-Location }

$ckpt = Join-Path $absOut "checkpoints\last\pretrained_model"
if (Test-Path $ckpt) { Write-Ok "权重: $ckpt" } else { Write-Warn2 "未找到 $ckpt" }
