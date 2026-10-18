# ============================================================================
#  repair-paths - 项目搬家后的路径修复 + 自检
#
#  用途：把整个项目目录移动到别的路径（例如从含中文的路径换到 D:\LeRobot）后，
#        修复那些「写死了旧绝对路径」的东西，并做一次完整自检。
#
#  为什么需要它：搬家后只有下面 3 处会失效，其余全部是路径无关的
#    1) .venv\Lib\site-packages\__editable__.lerobot-*.pth
#       内容是一行旧绝对路径 -> import lerobot 直接失败
#    2) lerobot\outputs\train\*\checkpoints\last
#       这是 Windows 目录 junction，目标记的是旧绝对路径 -> 变成悬空链接
#    3) ...\checkpoints\last\pretrained_model\train_config.json
#       里面的 output_dir 是旧路径 -> 只影响 -Resume 续训（不修也能评估）
#
#  不受影响（无需处理）：
#    · scripts\* / _tools\*  全部用 $PSScriptRoot / __file__ 推导路径
#    · config.ps1            只有串口、ID、相机序列号、repo_id
#    · .venv\pyvenv.cfg      指向系统 Python（D:\python），与项目位置无关
#    · lerobot\.git          没有 core.worktree 之类的绝对绑定
#    · 数据集与校准文件       在 %USERPROFILE%\.cache\huggingface\lerobot\ 下，
#                            根本不在项目目录里，搬家完全不影响
#
#  用法（在【新位置】的 scripts\ 目录下运行）:
#    powershell -ExecutionPolicy Bypass -File scripts\repair-paths.ps1
#    powershell -ExecutionPolicy Bypass -File scripts\repair-paths.ps1 -CheckOnly
# ============================================================================
[CmdletBinding()]
param(
    # 只检查、不修改
    [switch]$CheckOnly,
    # 同时修正 train_config.json 里的 output_dir（默认修）
    [switch]$SkipTrainConfig
)

$ErrorActionPreference = "Stop"
. (Join-Path $PSScriptRoot "_common.ps1")

$Root = $script:RootDir
Write-Host ""
Write-Host "  项目根目录: $Root" -ForegroundColor Cyan
Write-Host ""

$fixed = 0
$problems = @()

# ---------------------------------------------------------------------------
# 1) .venv 里的 editable 安装（最关键 —— 不修就 import 不了 lerobot）
# ---------------------------------------------------------------------------
Write-Step "1) .venv 的 editable 安装指向"
$sp = Join-Path $script:VenvDir "Lib\site-packages"
$pths = @()
if (Test-Path $sp) { $pths = Get-ChildItem $sp -Filter "__editable__*lerobot*.pth" -File -ErrorAction SilentlyContinue }
if (-not $pths) {
    $pths = Get-ChildItem $sp -Filter "*.pth" -File -ErrorAction SilentlyContinue |
        Where-Object { (Get-Content $_.FullName -Raw -ErrorAction SilentlyContinue) -match "lerobot" }
}

if (-not $pths) {
    Write-Warn2 "没找到 lerobot 的 .pth 文件 —— 虚拟环境可能没装成 editable，请重跑 scripts\setup-env.ps1"
    $problems += ".pth 缺失"
} else {
    $want = Join-Path $Root "lerobot\src"
    foreach ($pth in $pths) {
        $lines = @(Get-Content $pth.FullName -Encoding UTF8 -ErrorAction SilentlyContinue)
        $oldLine = ($lines | Where-Object { $_ -match "lerobot" } | Select-Object -First 1)
        $ok = ($oldLine -eq $want)
        Write-Host ("  文件: {0}" -f $pth.Name)
        Write-Host ("    当前: {0}" -f $oldLine)
        Write-Host ("    期望: {0}" -f $want)
        if ($ok) {
            Write-Ok "已经是新路径，无需修改"
        } elseif ($CheckOnly) {
            Write-Warn2 "路径不符（CheckOnly 模式未修改）"
            $problems += "$($pth.Name) 指向旧路径"
        } else {
            # 只替换含 lerobot 的那一行，保留其余行
            $newLines = $lines | ForEach-Object { if ($_ -match "lerobot") { $want } else { $_ } }
            if (-not $newLines) { $newLines = @($want) }
            [System.IO.File]::WriteAllLines($pth.FullName, $newLines, (New-Object System.Text.UTF8Encoding($false)))
            $chk = (Get-Content $pth.FullName -Encoding UTF8 | Where-Object { $_ -match "lerobot" } | Select-Object -First 1)
            if ($chk -eq $want) { Write-Ok "已改为新路径"; $fixed++ }
            else { Write-Bad "写入后校验失败"; $problems += "$($pth.Name) 写入失败" }
        }
    }
}

# ---------------------------------------------------------------------------
# 2) checkpoints\last 这个 junction
# ---------------------------------------------------------------------------
Write-Step "2) checkpoints\last（Windows 目录 junction）"
$ckRoot = Join-Path $Root "lerobot\outputs\train"
$lastDirs = @()
if (Test-Path $ckRoot) {
    Get-ChildItem $ckRoot -Directory -ErrorAction SilentlyContinue | ForEach-Object {
        $ck = Join-Path $_.FullName "checkpoints"
        if (Test-Path $ck) { $lastDirs += (Join-Path $ck "last") }
    }
}
if (-not $lastDirs) {
    Write-Warn2 "没找到任何 checkpoints\last（还没训练过，正常）"
} else {
    foreach ($last in $lastDirs) {
        $parent = Split-Path $last -Parent
        # 选步数最大的检查点作为目标
        $targets = Get-ChildItem $parent -Directory -ErrorAction SilentlyContinue |
            Where-Object { $_.Name -match '^\d{6}$' } | Sort-Object Name -Descending
        if (-not $targets) { Write-Warn2 "$parent 里没有步数目录，跳过"; continue }
        $target = $targets[0].FullName
        Write-Host ("  last   : {0}" -f $last)
        Write-Host ("  目标   : {0}" -f $target)

        $isLink = $false
        $resolves = $false
        if (Test-Path $last) {
            $item = Get-Item $last -Force -ErrorAction SilentlyContinue
            $isLink = ($null -ne $item -and $null -ne $item.LinkType)
            $resolves = Test-Path (Join-Path $last "pretrained_model\config.json")
        }
        Write-Host ("  状态   : 存在={0}  是链接={1}  指向有效={2}" -f (Test-Path $last), $isLink, $resolves)

        if ($resolves) {
            Write-Ok "已指向有效检查点，无需修改"
            continue
        }
        if ($CheckOnly) {
            Write-Warn2 "无效链接（CheckOnly 模式未修改）"
            $problems += "$last 无效"
            continue
        }
        # 删除（悬空 junction 用 rmdir 只删链接本身，绝不动目标内容）
        if (Test-Path $last) {
            $item = Get-Item $last -Force -ErrorAction SilentlyContinue
            if ($null -ne $item -and $null -ne $item.LinkType) {
                & cmd /c rmdir "$last" 2>&1 | Out-Null
            } else {
                Remove-Item -LiteralPath $last -Recurse -Force -ErrorAction SilentlyContinue
            }
        }
        & cmd /c mklink /J "$last" "$target" 2>&1 | Out-Null
        if (Test-Path (Join-Path $last "pretrained_model\config.json")) {
            Write-Ok "已重建 junction -> $([System.IO.Path]::GetFileName($target))"
            $fixed++
        } else {
            Write-Bad "重建失败，请手动执行: cmd /c mklink /J `"$last`" `"$target`""
            $problems += "$last 重建失败"
        }
    }
}

# ---------------------------------------------------------------------------
# 3) train_config.json 里的 output_dir（只影响 -Resume）
# ---------------------------------------------------------------------------
Write-Step "3) train_config.json 的 output_dir"
$tcFiles = @()
if (Test-Path $ckRoot) {
    Get-ChildItem $ckRoot -Recurse -Filter "train_config.json" -File -ErrorAction SilentlyContinue |
        ForEach-Object { $tcFiles += $_.FullName }
}
if (-not $tcFiles) {
    Write-Warn2 "没找到 train_config.json"
} elseif ($SkipTrainConfig) {
    Write-Host "  已按 -SkipTrainConfig 跳过"
} else {
    foreach ($tc in $tcFiles) {
        try {
            $json = Get-Content $tc -Raw -Encoding UTF8 | ConvertFrom-Json
            $cur = $json.output_dir
            # 从相对 $ckRoot 的路径里取第一段作为 job_name
            # ...\outputs\train\<job>\checkpoints\<step>\pretrained_model\train_config.json
            $rel = $tc.Substring($ckRoot.Length).TrimStart('\')
            $jobName = ($rel -split '\\')[0]
            $newDir = Join-Path $Root "lerobot\outputs\train\$jobName"
            if ($cur -and $cur.Equals($newDir, [StringComparison]::OrdinalIgnoreCase)) {
                Write-Ok "output_dir 已匹配当前项目: $cur"
            } else {
                Write-Host ("  {0}" -f $tc)
                Write-Host ("    旧: {0}" -f $cur)
                Write-Host ("    新: {0}" -f $newDir)
                if ($CheckOnly) {
                    Write-Warn2 "output_dir 指向旧路径（CheckOnly 模式未修改）"
                    $problems += "train_config.json output_dir"
                } else {
                    $json.output_dir = $newDir
                    # 注意：不能用 Set-Content -Encoding UTF8
                    # PowerShell 5.1 那样写会加 UTF-8 BOM，而 json.loads 遇到 BOM 会报
                    # Unexpected UTF-8 BOM -> -Resume 续训直接失败。必须写无 BOM 的 UTF-8。
                    $jsonText = $json | ConvertTo-Json -Depth 60
                    [System.IO.File]::WriteAllText(
                        $tc, $jsonText, (New-Object System.Text.UTF8Encoding($false)))
                    Write-Ok "已更新 output_dir（只影响 -Resume 续训）"
                    $fixed++
                }
            }
        } catch {
            Write-Warn2 "解析失败，跳过: $_"
        }
    }
}

# ---------------------------------------------------------------------------
# 4) 自检
# ---------------------------------------------------------------------------
Write-Step "4) 自检"
Push-Location $Root
try {
    $probe = @'
import sys
try:
    import lerobot
    print(f"  [OK] import lerobot -> {lerobot.__file__}")
except Exception as e:
    print(f"  [XX] import lerobot 失败: {type(e).__name__}: {e}")
    sys.exit(1)
try:
    from lerobot.motors.feetech import FeetechMotorsBus
    from lerobot.policies.act.modeling_act import ACTPolicy
    print("  [OK] 关键子模块可导入")
except Exception as e:
    print(f"  [XX] 子模块导入失败: {e}")
    sys.exit(1)
'@
    $probe | Out-File -FilePath "_repair_probe.py" -Encoding utf8
    & $script:VenvPy "_repair_probe.py"
    $pyOk = ($LASTEXITCODE -eq 0)
    Remove-Item "_repair_probe.py" -ErrorAction SilentlyContinue
} finally {
    Pop-Location
}

Write-Host ""
if ($CheckOnly) {
    if ($problems) {
        Write-Warn2 ("发现 {0} 处需要修复：" -f $problems.Count)
        $problems | ForEach-Object { Write-Host "    - $_" }
        Write-Host "`n  去掉 -CheckOnly 再跑一次即可自动修复。"
    } else {
        Write-Ok "全部正常，无需修复"
    }
} else {
    Write-Ok ("修复完成，共改动 {0} 处" -f $fixed)
    if ($pyOk) { Write-Ok "Python 侧自检通过 —— 可以正常使用本项目了" }
    else { Write-Bad "Python 侧仍有问题，请检查上面的报错" }
    Write-Host "`n  建议再跑一次评估预演确认整条链路：" -ForegroundColor Cyan
    Write-Host "    powershell -ExecutionPolicy Bypass -File scripts\10-eval.ps1 ``"
    Write-Host "      -PolicyPath lerobot\outputs\train\act_m1_pick_cube\checkpoints\last\pretrained_model ``"
    Write-Host "      -RepoId seeedstudio123/eval_check -NumEpisodes 1 -DryRun"
}
Write-Host ""
