# ============================================================================
#  10 - 策略上机评估（用训练好的策略驱动真机并录制评估数据集）
#
#  原理：lerobot-record 带上 --policy.path 后就不再用 Leader 遥操作，
#        而是由策略输出动作，同时把过程录成 eval_ 开头的新数据集。
#
#  用法:
#    powershell -ExecutionPolicy Bypass -File scripts\10-eval.ps1 -PolicyPath outputs/train/act_m1_pick_cube/checkpoints/last/pretrained_model
#    powershell -ExecutionPolicy Bypass -File scripts\10-eval.ps1 -PolicyPath <路径> -NumEpisodes 10 -EpisodeTimeS 50
#
#  注意:
#    - 相机键名（front / side / orbbec_color ...）必须与采集训练集时完全一致，
#      否则会报 `mean is infinity`。
#    - 若提示 eval_xxx 目录已存在，删掉该目录再跑。
#
#  【重要】-WithTeleop：强烈建议评估时加上
#    不带遥操作时，回合之间的 reset 阶段【没有任何动作来源】：
#      · 机械臂不会回到起始姿势（保持上一回合结束的姿态）
#      · 方块也只能靠手摆，机械臂却挡着
#    结果就是每条 episode 都从"姿态+方块位置都随机"的状态开始 ——
#    这不是训练时的分布，成功率会被严重低估（实测 0/10）。
#    加上 -WithTeleop 后：
#      · 回合中：仍由【策略】驱动（policy 分支优先于 teleop 分支）
#      · reset 中：由【Leader 主臂】驱动，你可以把从臂开回起始位，同时摆方块
#    这正是 LeRobot 官方推荐的评估方式。
# ============================================================================
[CmdletBinding()]
param(
    [Parameter(Mandatory=$true)][string]$PolicyPath,
    [string]$RepoId,
    [string]$Task,
    [int]$NumEpisodes = 10,
    [double]$EpisodeTimeS = 30,
    [double]$ResetTimeS = 15,
    # 评估时接上 Leader 主臂，用于 reset 阶段复位
    # （若用了下面的 -ResetHomePose 自动复位，就不用这个了）
    [switch]$WithTeleop,
    # >0 时覆盖策略的 n_action_steps：越小闭环修正越频繁（100=每次开环执行 3.3 秒）
    [int]$NActionSteps = 0,
    # 启用 ACT 的 temporal ensembling（对重叠的动作块做指数加权平均，显著提升鲁棒性）
    # ACT 要求启用它时 n_action_steps 必须为 1，脚本会自动处理
    [switch]$TemporalEnsemble,
    [double]$EnsembleCoeff = 0.01,
    # reset 阶段自动回到的起始姿势（归一化值：体关节 -100~100，夹爪 0~100）
    # 默认值 = 训练数据 98 条 episode 起始姿态的平均
    # 传空字符串 "" 可关闭自动复位
    [string]$ResetHomePose = "shoulder_pan:-33,shoulder_lift:13,elbow_flex:-15,wrist_flex:88,wrist_roll:-2,gripper:17",
    # 每帧最大移动量（归一化单位，相对当前位置）。
    # >0 时映射到 --robot.max_relative_target，用作安全限速：
    # 策略振荡时机械臂不会快速来回甩。建议 4~6；0 表示不限制。
    # 参考：4 单位/帧 ≈ 2.2°/帧 ≈ 67°/s。
    [double]$MaxStep = 0,
    # 动作一阶低通系数（0~1，映射到 --action_smooth）。
    # 用于压制"策略逐段重规划导致的原地快速摇摆"：
    #   0.5  = 推荐值，抖动约减半，轨迹滞后约 1 帧
    #   0.35 = 更平滑、滞后更大
    #   0.7  = 更跟手、抑抖弱
    #   1.0  = 关闭（原行为）
    # 注意：n_action_steps=100（默认）时动作本身已经很顺滑，
    #       低通主要用于 n_action_steps 较小或启用 temporal ensemble 时。
    [double]$ActionSmooth = 1.0,
    # 逐帧动作日志（CSV 路径）。给出即启用，用于事后分析抖动/fps。
    # 每条会单独写成 xxx.ep00.csv / xxx.ep01.csv …
    [string]$ActionLog = "",
    # 同名评估数据集已存在时：续录（保留已有数据）
    [switch]$Resume,
    # 同名评估数据集已存在时：删掉重跑
    [switch]$Overwrite,
    # 只打印将要执行的命令、不实际运行（用于确认参数）
    [switch]$DryRun,
    [switch]$NoCamera,
    [switch]$NoDisplay
)

$ErrorActionPreference = "Stop"
. (Join-Path $PSScriptRoot "_common.ps1")
$Cfg = Import-LerobotConfig
Initialize-LerobotEnv
Show-SafetyNotice
Test-PortsConfigured | Out-Null

if (-not $RepoId) { $RepoId = "seeedstudio123/eval_$($Cfg.JobName)" }
if (-not $Task)   { $Task   = $Cfg.Task }

# 相对路径解析：依次尝试 lerobot 仓库根目录、项目根目录
# （因为 Invoke-Lerobot 不切换 CWD，相对路径能否生效取决于你从哪里启动脚本。
#   这里显式解析成绝对路径，避免"以为加载本地权重、实际去 Hub 下载"的坑。）
if (-not [System.IO.Path]::IsPathRooted($PolicyPath)) {
    foreach ($base in @($script:RepoDir, $script:RootDir)) {
        $cand = Join-Path $base $PolicyPath
        if (Test-Path $cand) { $PolicyPath = $cand; break }
    }
}
if (-not (Test-Path $PolicyPath)) {
    Write-Warn2 "本地找不到 $PolicyPath"
    Write-Warn2 "如果这不是一个 HuggingFace 仓库名，请检查路径（应含 pretrained_model\config.json）"
} else {
    $cfgFile = Join-Path $PolicyPath "config.json"
    if (-not (Test-Path $cfgFile)) {
        Write-Warn2 "$PolicyPath 存在但缺少 config.json —— 确认它指向 ...\pretrained_model 目录"
    }
}

# ============================================================================
#  同名评估数据集已存在时的处理
#  LeRobot 对已存在的 repo_id 会抛 FileExistsError（WinError 183），
#  所以必须先决定：续录 / 删除重跑 / 换个名字。
# ============================================================================
# repo_id 形如 "owner/name"（正斜杠），落到磁盘是 "owner\name"（反斜杠）。
# 这里统一规范化，避免后面 Split-Path / -like 因分隔符不一致误判。
$repoParts = $RepoId -split '/'
$RepoLeaf  = $repoParts[-1]
$RepoOwner = if ($repoParts.Count -ge 2) { $repoParts[-2] } else { "" }
$dsDir = Join-Path (Join-Path $env:USERPROFILE ".cache\huggingface\lerobot") ($repoParts -join '\')
Write-Host "    评估数据目录: $dsDir" -ForegroundColor DarkGray
if (Test-Path $dsDir) {
    # 安全阀：只允许删除「...\lerobot\<owner>\<name>」这种我们自己构造出来的路径
    $okToDelete = $false
    if ((Split-Path $dsDir -Leaf) -eq $RepoLeaf) {
        $ownerDir = Split-Path $dsDir -Parent
        if (([string]::IsNullOrEmpty($RepoOwner) -and ((Split-Path $ownerDir -Leaf) -eq "lerobot")) -or
            ((Split-Path $ownerDir -Leaf) -eq $RepoOwner)) {
            $okToDelete = $true
        }
    }
    if ($Resume) {
        # 有 meta/info.json 才能续，否则脚本会报别的错
        if (-not (Test-Path (Join-Path $dsDir "meta\info.json"))) {
            Write-Bad "无法续录：$dsDir 缺少 meta\info.json（上次运行没写完整）"
            Write-Host "    请改用 -Overwrite 删除后重跑。" -ForegroundColor Yellow
            exit 1
        }
        Write-Host "    续录模式：将在已有数据集上追加（数据保留）" -ForegroundColor Cyan
    }
    elseif ($Overwrite) {
        if (-not $okToDelete) {
            Write-Bad "拒绝删除：路径校验未通过"
            Write-Host "      $dsDir"
            Write-Host "      期望：...\lerobot\$RepoOwner\$RepoLeaf" -ForegroundColor Yellow
            Write-Host "    请手动确认后自行删除。" -ForegroundColor Yellow
            exit 1
        }
        if ($DryRun) {
            Write-Host "    [DryRun] 本会删除该目录，但 DryRun 下不做任何改动：" -ForegroundColor Yellow
            Write-Host "             $dsDir"
        } else {
            Write-Host "    删除旧数据集：$dsDir" -ForegroundColor Yellow
            Remove-Item -Recurse -Force $dsDir
        }
    }
    else {
        $eps = "?"
        $infoF = Join-Path $dsDir "meta\info.json"
        if (Test-Path $infoF) {
            try { $eps = (Get-Content $infoF -Raw | ConvertFrom-Json).total_episodes } catch { $eps = "读取失败" }
        }
        Write-Bad "评估数据集已存在，LeRobot 不会覆盖它："
        Write-Host "      $dsDir"
        Write-Host "      现有 episode 数: $eps"
        Write-Host ""
        Write-Host "    三种处理方式（选一个）：" -ForegroundColor Yellow
        Write-Host "      -Resume      在原有数据上继续录到 $NumEpisodes 条（推荐，不浪费已录的）"
        Write-Host "      -Overwrite   删掉重来"
        Write-Host "      -RepoId xxx  换一个新的数据集名"
        Write-Host ""
        Write-Host "    打分现有数据： python _tools\eval_score.py $($RepoId.Split('/')[-1])" -ForegroundColor DarkGray
        exit 1
    }
}

$argv = @(
    "--robot.type=so101_follower",
    "--robot.port=$($Cfg.FollowerPort)",
    "--robot.id=$($Cfg.FollowerId)",
    "--dataset.repo_id=$RepoId",
    "--dataset.single_task=$Task",
    "--dataset.num_episodes=$NumEpisodes",
    "--dataset.episode_time_s=$EpisodeTimeS",
    "--dataset.reset_time_s=$ResetTimeS",
    "--dataset.push_to_hub=false",
    "--policy.path=$PolicyPath"
)
if ($Resume) { $argv += "--resume=true" }
if (-not $NoCamera) { $argv += Get-CameraArg }
if ($Cfg.DisplayData -and -not $NoDisplay) { $argv += "--display_data=true" }
$argv += "--play_sounds=false"

# 接上 Leader 主臂：回合内仍由策略驱动，reset 阶段才用它复位
if ($WithTeleop) {
    $argv += @(
        "--teleop.type=so101_leader",
        "--teleop.port=$($Cfg.LeaderPort)",
        "--teleop.id=$($Cfg.LeaderId)"
    )
}
# 覆盖每次开环执行的步数（默认 100 步 = 3.3 秒才修正一次）
if ($NActionSteps -gt 0) { $argv += "--policy.n_action_steps=$NActionSteps" }
# temporal ensembling：ACT 要求 n_action_steps=1
if ($TemporalEnsemble) {
    $argv += "--policy.n_action_steps=1"
    $argv += "--policy.temporal_ensemble_coeff=$EnsembleCoeff"
}
# reset 阶段自动回到固定起始姿势（只有不接遥操作时才有意义）
$autoHome = (-not $WithTeleop) -and $ResetHomePose
if ($autoHome) { $argv += "--reset_home_pose=$ResetHomePose" }
# 安全限速：限制每帧相对当前位置的最大移动量
if ($MaxStep -gt 0) { $argv += "--robot.max_relative_target=$MaxStep" }
# 动作低通：压制策略逐段重规划造成的原地抖动
if ($ActionSmooth -gt 0 -and $ActionSmooth -lt 1) { $argv += "--action_smooth=$ActionSmooth" }
# 逐帧动作日志（诊断用）
if ($ActionLog) { $argv += "--action_log_path=$ActionLog" }

Write-Host ">>> 策略评估：$PolicyPath" -ForegroundColor Cyan
Write-Host "    评估数据集: $RepoId"
Write-Host "    回合数: $NumEpisodes  每回合 ${EpisodeTimeS}s  reset ${ResetTimeS}s"
if ($WithTeleop) {
    Write-Host "    reset 阶段复位: Leader 主臂（手动把从臂开回起始位）"
} elseif ($autoHome) {
    Write-Host "    reset 阶段复位: ✅ 自动回到固定起始姿势（你只需要摆方块）"
    Write-Host "        $ResetHomePose"
} else {
    Write-Host "    reset 阶段复位: ⚠ 无 —— 机械臂不会回起始位，成功率会被低估" -ForegroundColor Yellow
}
if ($TemporalEnsemble) {
    Write-Host "    temporal ensembling 已启用（coeff=$EnsembleCoeff, n_action_steps=1，每帧重新规划 + 加权平均）"
} elseif ($NActionSteps -gt 0) {
    Write-Host "    n_action_steps 覆盖为 $NActionSteps（每 $([math]::Round($NActionSteps/30,2)) 秒重新规划）"
}
if ($MaxStep -gt 0) {
    Write-Host "    安全限速: 每帧最多 $MaxStep 单位（≈$([math]::Round($MaxStep/200*226,1))°/帧 ≈ $([math]::Round($MaxStep/200*226*30,0))°/s）"
}
if ($ActionSmooth -gt 0 -and $ActionSmooth -lt 1) {
    Write-Host "    动作低通: alpha=$ActionSmooth（抖动约减半，轨迹滞后约 $([math]::Round((1-$ActionSmooth)/$ActionSmooth,1)) 帧）"
}
Write-Host "    提示: 运行中按 x = 急停（丢弃当前条并结束），空格 = 暂停" -ForegroundColor DarkGray
Write-Host ""

if ($DryRun) {
    Write-Host "[DryRun] 将要执行的命令（未实际运行）：" -ForegroundColor Yellow
    Write-Host "  lerobot-record "
    $argv | ForEach-Object { Write-Host "    $_" }
    Write-Host "`n[DryRun] 去掉 -DryRun 即开始评估。" -ForegroundColor Yellow
    return
}

Invoke-Lerobot "lerobot-record" $argv

$dsPath = Join-Path $env:USERPROFILE ".cache\huggingface\lerobot\$RepoId"
if (Test-Path $dsPath) { Write-Ok "评估数据: $dsPath" }
