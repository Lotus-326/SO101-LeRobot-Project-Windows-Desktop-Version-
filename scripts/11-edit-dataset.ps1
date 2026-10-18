# ============================================================================
#  11 - 数据集工具（lerobot-edit-dataset）
#  对应官方 Wiki：https://wiki.seeedstudio.com/cn/lerobot_dataset_tool/
#
#  用法:
#    # 列出本地数据集
#    powershell -ExecutionPolicy Bypass -File scripts\11-edit-dataset.ps1 -Action list
#
#    # 查看某个数据集的信息
#    powershell -ExecutionPolicy Bypass -File scripts\11-edit-dataset.ps1 -Action info
#
#    # 删除 episode 0、2、5（直接改原数据集）
#    ... -Action delete-episodes -Episodes "0,2,5"
#
#    # 删除并另存为新数据集（保留原数据集）
#    ... -Action delete-episodes -Episodes "0,2,5" -NewRepoId seeedstudio123/m1_clean
#
#    # 按比例拆分 80/10/10
#    ... -Action split -Splits '{"train":0.8,"test":0.1,"val":0.1}'
#
#    # 按 episode 编号拆分
#    ... -Action split -Splits '{"task1":[0,1,2,3],"task2":[4,5]}'
#
#    # 合并多个数据集
#    ... -Action merge -RepoId seeedstudio123/m1_merged -RepoIds "seeedstudio123/a,seeedstudio123/b"
#
#    # 移除某个相机特征
#    ... -Action remove-feature -Features "observation.images.front"
#
#    # 修改任务描述
#    ... -Action modify-task -NewTask "把黑色方块放进盒子"
#
#    # 把图片数据集转成视频数据集
#    ... -Action convert-video -NewRepoId seeedstudio123/m1_video
#
#  说明:
#    为避免 PowerShell 传参时把 JSON 里的双引号搞坏，本脚本统一把参数
#    写成一个 JSON 配置文件，再用 `--config_path=<文件>` 调用
#    lerobot-edit-dataset。这样命令行里不含任何引号。
# ============================================================================
[CmdletBinding()]
param(
    [Parameter(Mandatory=$true)]
    [ValidateSet("list", "info", "delete-episodes", "split", "merge",
                 "remove-feature", "modify-task", "convert-video")]
    [string]$Action,

    [string]$RepoId,                    # 默认取 config.ps1 的 DatasetRepoId
    [string]$NewRepoId = "",
    [string]$Episodes = "",             # "0,2,5"
    [string]$Splits = "",               # JSON
    [string]$RepoIds = "",              # "a,b"
    [string]$Features = "",             # "observation.images.front"
    [string]$NewTask = "",
    [string]$EpisodeTasks = "",         # JSON
    [string]$OutputDir = "",
    [string]$VCodec = "libsvtav1",
    [int]$Crf = 30,
    [int]$NumWorkers = 4,
    [string]$LerobotHome = "",          # 想换数据存放根目录时用它（会设 HF_LEROBOT_HOME）
    [switch]$PushToHub,
    [switch]$ShowCommand,
    [switch]$DryRun
)

$ErrorActionPreference = "Stop"
. (Join-Path $PSScriptRoot "_common.ps1")
$Cfg = Import-LerobotConfig
Initialize-LerobotEnv

if (-not $RepoId) { $RepoId = $Cfg.DatasetRepoId }

# ---------------------------------------------------------------- 数据根目录
# 【踩坑记录】lerobot-edit-dataset 的 `--root` 语义在本版本里是【不一致】的：
#     LeRobotDatasetMetadata.__init__  : root 就是【数据集完整目录】
#     lerobot_edit_dataset.get_output_path : root 被当成【父目录】(root / repo_id)
#   所以传 --root 一定会有一边错。正确做法是【不传 root】，让它走默认的
#   HF_LEROBOT_HOME / repo_id；想换位置就设环境变量 HF_LEROBOT_HOME，
#   这样读和写两端会同步改变。
if ($LerobotHome) {
    $env:HF_LEROBOT_HOME = $LerobotHome
    Write-Host ">>> HF_LEROBOT_HOME = $LerobotHome" -ForegroundColor DarkGray
}
$dsRoot = if ($env:HF_LEROBOT_HOME) { $env:HF_LEROBOT_HOME } else { Join-Path $env:USERPROFILE ".cache\huggingface\lerobot" }
$localDs = Join-Path $dsRoot ($RepoId -replace '/', '\')
if (Test-Path (Join-Path $localDs "meta\info.json")) {
    Write-Host ">>> 本地数据集: $localDs" -ForegroundColor DarkGray
} else {
    Write-Warn2 "本地找不到 $localDs\meta\info.json"
    Write-Warn2 "lerobot-edit-dataset 会去 HuggingFace Hub 找，没网/没代理会卡住或报 401。"
}

function ConvertTo-IntList {
    param([string]$s)
    if ([string]::IsNullOrWhiteSpace($s)) { return @() }
    return @($s -split '[,;\s]+' | Where-Object { $_ -ne '' } | ForEach-Object { [int]$_ })
}

# ---------------------------------------------------------------- list / info
if ($Action -eq "list") {
    Write-Step "本地数据集（$dsRoot）"
    if (-not (Test-Path $dsRoot)) { Write-Warn2 "目录不存在，还没有录过数据集"; exit 0 }
    Get-ChildItem $dsRoot -Directory -Recurse -Depth 1 -ErrorAction SilentlyContinue |
        Where-Object { Test-Path (Join-Path $_.FullName "meta\info.json") } |
        ForEach-Object {
            $info = Get-Content (Join-Path $_.FullName "meta\info.json") -Raw -Encoding UTF8 | ConvertFrom-Json
            [pscustomobject]@{
                RepoId   = $_.FullName.Replace("$dsRoot\", "").Replace("\", "/")
                Episodes = $info.total_episodes
                Frames   = $info.total_frames
                Fps      = $info.fps
                SizeMB   = [math]::Round(((Get-ChildItem $_.FullName -Recurse -File | Measure-Object Length -Sum).Sum / 1MB), 1)
            }
        } | Format-Table -AutoSize
    exit 0
}

if ($Action -eq "info") {
    Write-Step "数据集信息: $RepoId"
    $p = Join-Path $dsRoot ($RepoId -replace '/', '\')
    if (-not (Test-Path "$p\meta\info.json")) { Write-Bad "找不到 $p\meta\info.json"; exit 1 }
    $info = Get-Content "$p\meta\info.json" -Raw -Encoding UTF8 | ConvertFrom-Json
    $info | ConvertTo-Json -Depth 4
    Write-Host "`n特征列表：" -ForegroundColor Cyan
    $info.features.PSObject.Properties | ForEach-Object {
        "  {0}  <-  {1}" -f $_.Name, ($_.Value.dtype)
    }
    Write-Host "`nEpisode 数: $($info.total_episodes)   帧数: $($info.total_frames)   fps: $($info.fps)"
    exit 0
}

# ---------------------------------------------------------------- 构造 operation
$operation = [ordered]@{}
switch ($Action) {
    "delete-episodes" {
        if ([string]::IsNullOrWhiteSpace($Episodes)) { throw "-Episodes 必填，例如 -Episodes '0,2,5'" }
        $operation.type = "delete_episodes"
        # 注意：PowerShell 函数返回数组时会「解包」，单元素会退化成标量，
        #       JSON 里就变成 "episode_indices": 1 而不是 [1]，draccus 直接拒绝。
        #       所以这里显式转成 [int[]]。
        $operation.episode_indices = [int[]](ConvertTo-IntList $Episodes)
    }
    "split" {
        if ([string]::IsNullOrWhiteSpace($Splits)) { throw "-Splits 必填，例如 -Splits '{`"train`":0.8,`"val`":0.2}'" }
        $operation.type = "split"
        # PS 5.1 没有 ConvertFrom-Json -AsHashtable，直接留 PSCustomObject，
        # ConvertTo-Json 会把它原样写回 JSON。
        $operation.splits = ($Splits | ConvertFrom-Json)
    }
    "merge" {
        if ([string]::IsNullOrWhiteSpace($RepoIds)) { throw "-RepoIds 必填，例如 -RepoIds 'user/a,user/b'" }
        $operation.type = "merge"
        $operation.repo_ids = [string[]]@($RepoIds -split '[,;\s]+' | Where-Object { $_ -ne '' })
    }
    "remove-feature" {
        if ([string]::IsNullOrWhiteSpace($Features)) { throw "-Features 必填，例如 -Features 'observation.images.front'" }
        $operation.type = "remove_feature"
        $operation.feature_names = [string[]]@($Features -split '[,;\s]+' | Where-Object { $_ -ne '' })
    }
    "modify-task" {
        $operation.type = "modify_tasks"
        if ($NewTask) { $operation.new_task = $NewTask }
        if ($EpisodeTasks) { $operation.episode_tasks = ($EpisodeTasks | ConvertFrom-Json) }
        if (-not $NewTask -and -not $EpisodeTasks) { throw "modify-task 需要 -NewTask 或 -EpisodeTasks" }
    }
    "convert-video" {
        $operation.type = "convert_image_to_video"
        if ($OutputDir) { $operation.output_dir = $OutputDir }
        $operation.vcodec = $VCodec
        $operation.pix_fmt = "yuv420p"
        $operation.g = 2
        $operation.crf = $Crf
        $operation.fast_decode = 0
        $operation.num_workers = $NumWorkers
    }
    default { throw "未支持的动作: $Action" }
}

$cfgObj = [ordered]@{
    repo_id     = $RepoId
    operation   = $operation
    push_to_hub = [bool]$PushToHub
}
if ($NewRepoId) { $cfgObj.new_repo_id = $NewRepoId }
# 故意不写 root：见文件开头关于 --root 语义不一致的说明。

# ---------------------------------------------------------------- 写配置文件
$outDir = Join-Path $script:RootDir "outputs\edit-configs"
New-Item -ItemType Directory -Force -Path $outDir | Out-Null
$stamp  = Get-Date -Format "yyyyMMdd-HHmmss"
$cfgPath = Join-Path $outDir "$Action-$stamp.json"
$json = $cfgObj | ConvertTo-Json -Depth 8
[System.IO.File]::WriteAllText($cfgPath, $json, (New-Object System.Text.UTF8Encoding($false)))

Write-Step "数据集操作: $Action"
Write-Host "  repo_id : $RepoId"
if ($NewRepoId) { Write-Host "  new     : $NewRepoId" }
Write-Host "  配置    : $cfgPath"
Write-Host ""
Write-Host $json -ForegroundColor DarkGray

if ($DryRun) { Write-Warn2 "-DryRun：只生成配置，不执行"; exit 0 }

Show-SafetyNotice
$argv = @("--config_path=$cfgPath")
if ($ShowCommand) { Write-Host "$ lerobot-edit-dataset $($argv -join ' ')" }

Push-Location $script:RepoDir
try { Invoke-Lerobot "lerobot-edit-dataset" $argv }
finally { Pop-Location }

Write-Host "`n>>> 用完可以重新查看: scripts\11-edit-dataset.ps1 -Action list" -ForegroundColor Cyan
