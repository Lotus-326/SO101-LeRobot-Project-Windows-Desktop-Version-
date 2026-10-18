# ============================================================================
#  12 - SO-ARM 舵机调试 / 中位校准工具（Seeed_RoboController）
#  对应官方 Wiki：https://wiki.seeedstudio.com/cn/lerobot_steering_gear_debugging_tool/
#
#  适用场景:
#    - 检查舵机 ID 是否正确、是否有重复 ID
#    - 写入中位值（把当前位置设为 2048）
#    - 单舵机点动、力矩开关、寄存器读写
#    - 排查 `Magnitude ... exceeds 2047` 之类的校准异常
#    - 管理 / 生成 LeRobot 校准文件
#
#  用法:
#    # 一次性安装（clone + 装依赖 + 环境检查）
#    powershell -ExecutionPolicy Bypass -File scripts\12-steering-tool.ps1 -Action setup
#
#    # 打开 GUI（最常用）
#    ... -Action gui
#    ... -Action gui -Port COM9 -Port2 COM10        # 指定主/从两个串口
#    ... -Action gui -List                          # 只列出可用串口
#
#    # 命令行工具
#    ... -Action scan                # 扫描总线上的舵机 ID（交互式）
#    ... -Action change-id           # 改单个舵机 ID（交互式）
#    ... -Action center-test         # 中位测试
#    ... -Action middle              # 按 LeRobot 校准文件写中位
#    ... -Action quick               # 快捷校准
#    ... -Action disable             # 失能电机（机械臂会软掉，扶好！）
#    ... -Action diag -Port COM9 -Id 3      # 读寄存器诊断
#    ... -Action limits -Port COM9   # 角度限位设置 GUI
#    ... -Action remote -Port COM9 -Port2 COM10   # 主从同步遥操作
# ============================================================================
[CmdletBinding()]
param(
    [ValidateSet("setup", "gui", "scan", "change-id", "center-test", "middle",
                 "quick", "disable", "diag", "limits", "remote")]
    [string]$Action = "gui",

    [string]$Port = "",
    [string]$Port2 = "",
    [int]$Id = 1,
    [ValidateSet("follower", "leader")]
    [string]$ArmType = "follower",
    [string]$CalibrationFile = "",
    [ValidateSet("zh", "en")]
    [string]$Lang = "zh",
    [switch]$List
)

$ErrorActionPreference = "Stop"
. (Join-Path $PSScriptRoot "_common.ps1")
$Cfg = Import-LerobotConfig
Initialize-LerobotEnv

$ToolDir = Join-Path $script:RootDir "tools\Seeed_RoboController"
$RepoUrl = "https://github.com/Seeed-Projects/Seeed_RoboController.git"

function Invoke-Rc {
    param([string[]]$Arguments)
    Push-Location $ToolDir
    try {
        Write-Host ""
        Write-Host "$ python $($Arguments -join ' ')" -ForegroundColor DarkGray
        $prev = $ErrorActionPreference
        $ErrorActionPreference = "Continue"
        try { & $script:VenvPy @Arguments } finally { $ErrorActionPreference = $prev }
        Write-Host "退出码: $LASTEXITCODE" -ForegroundColor DarkGray
    }
    finally { Pop-Location }
}

# --------------------------------------------------------------------- setup
if ($Action -eq "setup" -or -not (Test-Path $ToolDir)) {
    Write-Step "安装 / 准备 Seeed_RoboController"
    if (-not (Test-Path $ToolDir)) {
        Write-Host "-> clone $RepoUrl"
        New-Item -ItemType Directory -Force -Path (Split-Path $ToolDir) | Out-Null
        git clone --depth 1 $RepoUrl $ToolDir
        if ($LASTEXITCODE -ne 0) { throw "clone 失败（GitHub 需要代理，见 docs/09-Windows排障FAQ.md A1）" }
    } else {
        Write-Ok "仓库已存在: $ToolDir"
    }

    Write-Host "-> 安装依赖 PySide6 + pyserial"
    # PySide6 全套含 Qt 3D/WebEngine，很大；本工具只用 QtCore/QtGui/QtWidgets，
    # 装 PySide6-Essentials 即可（清华镜像没有 PySide6，走官方源 + 代理）。
    $env:HTTP_PROXY = $Cfg.Proxy; $env:HTTPS_PROXY = $Cfg.Proxy; $env:NO_PROXY = "localhost,127.0.0.1,::1"
    & $script:VenvPy -m pip install "PySide6-Essentials" "pyserial>=3.5" `
        --index-url https://pypi.org/simple --retries 5 --timeout 180
    if ($LASTEXITCODE -ne 0) { Write-Warn2 "PySide6 安装失败，试试先开好代理再重跑" }

    $env:HTTP_PROXY = ""; $env:HTTPS_PROXY = ""; $env:NO_PROXY = "*"
    Invoke-Rc @("setup.py")
    if ($Action -eq "setup") {
        Write-Ok "安装完成。用 -Action gui 打开图形界面。"
        exit 0
    }
}

# ------------------------------------------------------------ 默认串口/校准文件
if (-not $Port) { $Port = $Cfg.FollowerPort }
if (-not $Port2 -and $Cfg.LeaderPort -ne $Port) { $Port2 = $Cfg.LeaderPort }

if (-not $CalibrationFile) {
    $sub = if ($ArmType -eq "leader") { "teleoperators" } else { "robots" }
    $rid = if ($ArmType -eq "leader") { $Cfg.LeaderId } else { $Cfg.FollowerId }
    $CalibrationFile = Join-Path $env:USERPROFILE ".cache\huggingface\lerobot\calibration\$sub\$rid.json"
}

# 用户是否【显式】传了 -Port / -Port2？
# gui / scan / diag 这类动作只在显式传参时才用配置里的串口 ——
# 否则 config.ps1 里还是占位值（本机 COM4/COM5 其实是蓝牙口），会把人带沟里。
$PortGiven  = $PSBoundParameters.ContainsKey("Port")
$Port2Given = $PSBoundParameters.ContainsKey("Port2")

Write-Step "Seeed_RoboController - $Action"
Write-Host "  工具目录 : $ToolDir"
if ($PortGiven -or $Port2Given) {
    $shown = @()
    if ($PortGiven)  { $shown += $Port }
    if ($Port2Given) { $shown += $Port2 }
    Write-Host "  串口     : $($shown -join ' / ')"
} else {
    Write-Host "  串口     : （未指定，工具内交互式选择）"
}
if ($Action -eq "middle") { Write-Host "  校准文件 : $CalibrationFile" }

switch ($Action) {
    "gui" {
        Show-SafetyNotice
        $a = @("-m", "src.gui.factory_calibration_tool", "--lang", $Lang)
        if ($List) { $a += "--list-ports" }
        else {
            if ($PortGiven)  { $a += @("--port1", $Port) }
            if ($Port2Given) { $a += @("--port2", $Port2) }
        }
        Write-Host "GUI 窗口会弹出来（界面里可自己选串口）；关掉窗口即退出。" -ForegroundColor Yellow
        Invoke-Rc $a
    }
    "limits" {
        Show-SafetyNotice
        $a = @("-m", "src.gui.servo_angle_limit_set", "--lang", $Lang)
        if ($List) { $a += "--list-ports" } elseif ($PortGiven) { $a += @("--port", $Port) }
        Invoke-Rc $a
    }
    "scan" {
        Show-SafetyNotice
        if ($List) { Invoke-Rc @("-m", "src.tools.scan_id", "--list") }
        elseif ($PortGiven) { Invoke-Rc @("-m", "src.tools.scan_id", $Port) }
        else { Invoke-Rc @("-m", "src.tools.scan_id") }
    }
    "change-id" {
        Show-SafetyNotice
        Write-Warn2 "改 ID 前请确保总线上【只接着要改的那一个舵机】，否则同 ID 的舵机会被一起改掉！"
        Invoke-Rc @("-m", "src.tools.change_single_servo_id")
    }
    "center-test" { Show-SafetyNotice; Invoke-Rc @("-m", "src.tools.servo_center_test") }
    "quick"       { Show-SafetyNotice; Invoke-Rc @("-m", "src.tools.servo_quick_calibration") }
    "disable"     { Show-SafetyNotice; Write-Warn2 "失能后机械臂会软掉，请用手扶住！"; Invoke-Rc @("-m", "src.tools.servo_disable") }
    "middle" {
        Show-SafetyNotice
        if (-not (Test-Path $CalibrationFile)) {
            Write-Bad "找不到校准文件: $CalibrationFile"
            Write-Host "  先跑 scripts\03-calibrate.ps1 -Arm $ArmType 生成它，或用 -CalibrationFile 指定别的文件"
            exit 1
        }
        Invoke-Rc @("-m", "src.tools.run_calibration_middle", $CalibrationFile, $Port)
    }
    "diag" {
        $a = @("-m", "src.tools.servo_register_diag")
        if ($PortGiven) { $a += $Port }
        $a += @("--id", "$Id")
        Invoke-Rc $a
    }
    "remote" {
        Show-SafetyNotice
        if (-not ($PortGiven -and $Port2Given)) {
            Write-Bad "-Action remote 需要同时指定 -Port 和 -Port2（主控/从控两个串口）"
            exit 1
        }
        Invoke-Rc @("-m", "src.tools.servo_remote_control", "--read-port", $Port, "--control-port", $Port2)
    }
}
