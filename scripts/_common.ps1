# ============================================================================
#  公共函数库（被其它脚本 dot-source，不要直接运行）
# ============================================================================

$script:RootDir     = Split-Path -Parent $PSScriptRoot
$script:VenvDir     = Join-Path $script:RootDir ".venv"
$script:VenvScripts = Join-Path $script:VenvDir "Scripts"
$script:VenvPy      = Join-Path $script:VenvScripts "python.exe"
$script:RepoDir     = Join-Path $script:RootDir "lerobot"
$script:FfmpegBin   = Join-Path $script:RootDir "tools\ffmpeg-master-latest-win64-gpl\bin"

function Write-Step  { param([string]$m) Write-Host "`n>>> $m" -ForegroundColor Cyan }
function Write-Ok    { param([string]$m) Write-Host "  [OK] $m" -ForegroundColor Green }
function Write-Warn2 { param([string]$m) Write-Host "  [!!] $m" -ForegroundColor Yellow }
function Write-Bad   { param([string]$m) Write-Host "  [XX] $m" -ForegroundColor Red }

function Import-LerobotConfig {
    <# 读取 config.ps1 到 $Cfg #>
    $cfgPath = Join-Path $PSScriptRoot "config.ps1"
    if (-not (Test-Path $cfgPath)) { throw "缺少配置文件：$cfgPath" }
    . $cfgPath
    if (-not $Cfg) { throw "config.ps1 未定义 `$Cfg" }
    return $Cfg
}

function Initialize-LerobotEnv {
    <#
      激活本项目的虚拟环境：
        - 把 .venv\Scripts 和 ffmpeg\bin 加到 PATH 最前面
        - 让 pip / huggingface 走代理（可选）
        - 设置 UTF-8，避免中文日志乱码
    #>
    if (-not (Test-Path $script:VenvPy)) {
        throw "未找到虚拟环境：$script:VenvPy`n请先运行：powershell -ExecutionPolicy Bypass -File scripts\setup-env.ps1"
    }

    $env:Path = "$script:VenvScripts;$script:FfmpegBin;$env:Path"
    $env:PYTHONUTF8 = "1"
    $env:PYTHONIOENCODING = "utf-8"
    # OpenCV 4.12 自带的 obsensor 后端在枚举相机索引时会疯狂打印
    # "cv::obsensor::getStreamChannelGroup Camera index out of range"。
    # 本项目访问 Orbbec 走的是 pyorbbecsdk（不是 OpenCV obsensor），关掉它即可。
    $env:OPENCV_VIDEOIO_PRIORITY_OBSENSOR = "0"
    try { [Console]::OutputEncoding = [System.Text.Encoding]::UTF8 } catch {}

    if ($Cfg.UseProxy -and $Cfg.Proxy) {
        $env:HTTP_PROXY  = $Cfg.Proxy
        $env:HTTPS_PROXY = $Cfg.Proxy
        $env:NO_PROXY    = "localhost,127.0.0.1,::1"
    }
    if ($Cfg.UseHfMirror) { $env:HF_ENDPOINT = $Cfg.HfMirror }

    if (-not (Get-Command lerobot-info -ErrorAction SilentlyContinue)) {
        Write-Warn2 "PATH 中未找到 lerobot-* 命令；请确认已执行 pip install -e . 或重新打开终端"
    }
}

function Show-SafetyNotice {
    Write-Host ""
    Write-Host "==============================================================" -ForegroundColor Red
    Write-Host " 安全提醒：运行前请清空机械臂 1 米范围内的贵重/易碎物品，" -ForegroundColor Red
    Write-Host " 固定好机械臂，确认电源与线缆连接可靠，人员保持安全距离。" -ForegroundColor Red
    Write-Host " 出现异响 / 异常运动 / 通信中断请立即 Ctrl+C 并断电检查。" -ForegroundColor Red
    Write-Host "==============================================================" -ForegroundColor Red
    Write-Host ""
}

function Test-PortsConfigured {
    <# 默认占位值提醒 #>
    if ($Cfg.FollowerPort -eq "COM4" -and $Cfg.LeaderPort -eq "COM5") {
        Write-Warn2 "串口仍是默认占位值（COM4 / COM5）。请先运行 scripts\01-find-port.ps1，把真实 COM 口填进 scripts\config.ps1"
        return $false
    }
    return $true
}

function Get-CameraArg {
    <# 生成 --robot.cameras=<spec>；Cameras 为空时返回空数组 #>
    if ([string]::IsNullOrWhiteSpace($Cfg.Cameras)) { return @() }
    return @("--robot.cameras=$($Cfg.Cameras)")
}

function Get-SerialPortInfo {
    <#
      快速列出串口。
      走注册表 HKLM:\HARDWARE\DEVICEMAP\SERIALCOMM，瞬间返回；
      不要用 Get-CimInstance Win32_PnPEntity —— 本机实测那个要 44 秒。

      返回对象: Port / Kind / DevicePath
        Kind = '蓝牙' -> BTHENUM 虚拟串口，找机械臂时忽略
        Kind = 'USB'  -> USB 转串口（CH340 / CP210x 等），机械臂就是它
        Kind = '其它'
    #>
    $map = @{}
    try {
        $rk = Get-ItemProperty -Path 'HKLM:\HARDWARE\DEVICEMAP\SERIALCOMM' -ErrorAction Stop
        foreach ($prop in $rk.PSObject.Properties) {
            if ($prop.Name -like 'PS*') { continue }
            $map[[string]$prop.Value] = $prop.Name
        }
    }
    catch { }

    $names = [System.IO.Ports.SerialPort]::GetPortNames() | Sort-Object
    foreach ($n in $names) {
        $path = [string]$map[$n]
        $kind = '其它'
        if ($path -match 'BTHENUM|BTHMODEM') { $kind = '蓝牙' }
        elseif ($path -match 'USB|VCP|SER') { $kind = 'USB' }
        [pscustomobject]@{ Port = $n; Kind = $kind; DevicePath = $path }
    }
}

function ConvertTo-ArgLine {
    <#
      把参数数组拼成一条命令行字符串，供 Start-Process -ArgumentList 使用。
      Start-Process 会把数组用空格 join 之后直接丢给 CreateProcess，
      含空格的参数（如 --robot.cameras={ front: {...} }）必须自己加引号，
      否则会被拆成多个参数。
      本项目所有参数内部都不含双引号（相机片段统一用单引号），所以只做简单包裹。
    #>
    param([string[]]$Arguments = @())
    $parts = foreach ($a in $Arguments) {
        if ($a -match '\s') { '"' + $a + '"' } else { $a }
    }
    return ($parts -join ' ')
}

function Invoke-Lerobot {
    <#
      调用 lerobot-* 命令，参数用数组一次性展开（避免 PowerShell 引号地狱）。
      用法： Invoke-Lerobot "lerobot-teleoperate" $argv

      注意：本函数【不返回值】，退出码放在 $script:LastLerobotExit。
      因为一旦 return 值，调用方为了吞掉它就会写 `| Out-Null`，
      那会把被调程序自己的 stdout 一起丢掉（tqdm 进度、相机列表全没了）。
    #>
    param(
        [Parameter(Mandatory=$true)][string]$Exe,
        [string[]]$Arguments = @()
    )
    Write-Host ""
    Write-Host "$ $Exe $($Arguments -join ' ')" -ForegroundColor DarkGray
    # 原生程序的 stderr 在 $ErrorActionPreference='Stop' 下会被 PS 当成错误抛出，
    # 这里临时放宽，否则 OpenCV/ffmpeg 的无害告警会中断脚本。
    $prev = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    try {
        & $Exe @Arguments
        $script:LastLerobotExit = $LASTEXITCODE
    }
    finally {
        $ErrorActionPreference = $prev
    }
    if ($script:LastLerobotExit -ne 0) { Write-Bad "$Exe 退出码 $script:LastLerobotExit" }
    else { Write-Ok "$Exe 执行完成" }
}
