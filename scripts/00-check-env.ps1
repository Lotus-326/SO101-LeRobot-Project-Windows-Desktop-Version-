# ============================================================================
#  00 - 环境自检
#  用法: powershell -ExecutionPolicy Bypass -File scripts\00-check-env.ps1
#
#  Python 侧的四项检查（torch/cuda、视频编码、机器人类型注册、Orbbec SDK）
#  交给 _tools\env_report.py，避免 PowerShell 5.1 多行字符串传参踩坑。
# ============================================================================
[CmdletBinding()]
param()

$ErrorActionPreference = "Stop"
. (Join-Path $PSScriptRoot "_common.ps1")
$Cfg = Import-LerobotConfig

Write-Host "================ LeRobot 环境自检 ================" -ForegroundColor Cyan

# ---------------------------------------------------------------- 1) Python
Write-Step "1) Python / 虚拟环境"
Write-Host "  解释器 : $script:VenvPy"
if (-not (Test-Path $script:VenvPy)) {
    Write-Bad "虚拟环境不存在，请先运行 scripts\setup-env.ps1"
    exit 1
}
Write-Ok "虚拟环境存在"
Initialize-LerobotEnv
& $script:VenvPy --version

# ------------------------------------------------- 2/3/6/7) 交给 Python 报告
$report = Join-Path $script:RootDir "_tools\env_report.py"
if (Test-Path $report) {
    & $script:VenvPy $report
    $pyExit = $LASTEXITCODE
} else {
    Write-Bad "缺少 _tools\env_report.py"
    $pyExit = 1
}

# ---------------------------------------------------------------- 4) ffmpeg
Write-Step "4) ffmpeg（命令行工具，备用）"
$ff = Join-Path $script:FfmpegBin "ffmpeg.exe"
if (Test-Path $ff) {
    $v = (& $ff -version 2>&1 | Select-Object -First 1)
    Write-Ok "ffmpeg: $v"
    $enc = (& $ff -hide_banner -encoders 2>&1 | Select-String 'libsvtav1')
    if ($enc) { Write-Ok "ffmpeg 含 libsvtav1 编码器" }
    else { Write-Warn2 "ffmpeg 不含 libsvtav1（PyAV 已内置，一般不影响采集）" }
} else {
    Write-Warn2 "未找到 tools\ffmpeg-*\bin\ffmpeg.exe（PyAV 已内置 FFmpeg，采集不受影响）"
}

# -------------------------------------------------------- 5) lerobot 命令
Write-Step "5) lerobot 命令行工具"
$cmds = @(
    "lerobot-calibrate", "lerobot-find-port", "lerobot-find-cameras",
    "lerobot-setup-motors", "lerobot-teleoperate", "lerobot-record",
    "lerobot-replay", "lerobot-dataset-viz", "lerobot-train", "lerobot-eval",
    "lerobot-info", "lerobot-edit-dataset"
)
$missing = @()
foreach ($c in $cmds) {
    if (Get-Command $c -ErrorAction SilentlyContinue) { Write-Host "  [OK] $c" -ForegroundColor Green }
    else { Write-Host "  [XX] $c 缺失" -ForegroundColor Red; $missing += $c }
}
if ($missing.Count) { Write-Warn2 "缺失命令：$($missing -join ', ')。请重跑 setup-env.ps1" }

# ---------------------------------------------------------------- 8) 串口
Write-Step "8) 串口"
$info = @(Get-SerialPortInfo)
if ($info.Count) {
    $info | Format-Table Port, Kind, DevicePath -AutoSize | Out-String -Width 200 | Write-Host
    $usb = $info | Where-Object { $_.Kind -eq 'USB' }
    if ($usb) { Write-Ok ("USB 转串口: " + ($usb.Port -join ', ')) }
    else { Write-Warn2 "没有 USB 转串口设备（机械臂没插？还是只看到蓝牙虚拟串口？）" }
} else {
    Write-Warn2 "未检测到任何 COM 口（机械臂没插？）"
}

# ---------------------------------------------------------------- 9) 配置
Write-Step "9) 当前配置（scripts\config.ps1）"
Write-Host "  Follower 串口/ID : $($Cfg.FollowerPort) / $($Cfg.FollowerId)"
Write-Host "  Leader   串口/ID : $($Cfg.LeaderPort) / $($Cfg.LeaderId)"
Write-Host "  相机             : $($Cfg.Cameras)"
Write-Host "  数据集           : $($Cfg.DatasetRepoId)"
Write-Host "  任务描述         : $($Cfg.Task)"
Write-Host "  训练输出         : $($Cfg.OutputDir)"
Test-PortsConfigured | Out-Null

# ---------------------------------------------------------------- 10) 校准
Write-Step "10) 校准文件"
$calibRoot = Join-Path $env:USERPROFILE ".cache\huggingface\lerobot\calibration"
Write-Host "  目录: $calibRoot"
if (Test-Path $calibRoot) {
    $files = Get-ChildItem $calibRoot -Recurse -File -ErrorAction SilentlyContinue
    if ($files) { $files | ForEach-Object { Write-Host "    $($_.FullName)" } }
    else { Write-Warn2 "目录存在但还没有校准文件" }
} else { Write-Warn2 "还没有校准文件（正常，第一次校准后才会生成）" }

# ------------------------------------------------------- 11) 相机片段解析
Write-Step "11) 相机配置片段解析（不接硬件，只验语法）"
$checkScript = Join-Path $script:RootDir "_tools\check_cameras_spec.py"
if (Test-Path $checkScript) { & $script:VenvPy $checkScript $Cfg.Cameras }
else { Write-Warn2 "缺少 _tools\check_cameras_spec.py" }

# ---------------------------------------------------------------- 汇总
Write-Host ""
if ($pyExit -eq 0) {
    Write-Host "================ 自检结束：Python 侧全部通过 ================" -ForegroundColor Green
} else {
    Write-Host "================ 自检结束：有项目未通过，见上方 [XX] ================" -ForegroundColor Yellow
}
