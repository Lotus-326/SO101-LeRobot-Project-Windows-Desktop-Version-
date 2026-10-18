# ============================================================================
#  01 - 查找机械臂串口 (Windows: COMx)
#
#  用法:
#    powershell -ExecutionPolicy Bypass -File scripts\01-find-port.ps1
#    ... -Interactive                 # 调 lerobot-find-port 做插拔比对
#    ... -SetFollower COM9 -SetLeader COM10   # 查到后直接写回 config.ps1
#
#  说明: 走注册表 HKLM:\HARDWARE\DEVICEMAP\SERIALCOMM，瞬间出结果。
#        （Get-CimInstance Win32_PnPEntity 在本机要 44 秒，故不采用）
# ============================================================================
[CmdletBinding()]
param(
    [switch]$Interactive,
    [string]$SetFollower = "",
    [string]$SetLeader = ""
)

$ErrorActionPreference = "Stop"
. (Join-Path $PSScriptRoot "_common.ps1")
$Cfg = Import-LerobotConfig
Initialize-LerobotEnv

function Set-ConfigPort {
    <# 把 COM 口号写回 config.ps1，保留 UTF-8 BOM（否则 PS 5.1 会读成乱码） #>
    param([string]$Key, [string]$Value)
    $cfgPath = Join-Path $PSScriptRoot "config.ps1"
    $text = [System.IO.File]::ReadAllText($cfgPath, [System.Text.Encoding]::UTF8)
    $pattern = "(?m)^(\s*$Key\s*=\s*"")[^""]*("")"
    if ($text -notmatch $pattern) { Write-Warn2 "config.ps1 里没找到 $Key，跳过"; return }
    $new = [regex]::Replace($text, $pattern, "`${1}$Value`${2}")
    [System.IO.File]::WriteAllText($cfgPath, $new, (New-Object System.Text.UTF8Encoding($true)))
    Write-Ok "已写入 $Key = `"$Value`""
}

if ($SetFollower -or $SetLeader) {
    Write-Step "写回 config.ps1"
    if ($SetFollower) { Set-ConfigPort -Key "FollowerPort" -Value $SetFollower }
    if ($SetLeader)   { Set-ConfigPort -Key "LeaderPort"   -Value $SetLeader }
    Write-Host "`n>>> 校验一下：" -ForegroundColor Cyan
    Write-Host "    powershell -ExecutionPolicy Bypass -File scripts\00-check-env.ps1"
    exit 0
}

Write-Host "================ 串口一览 ================" -ForegroundColor Cyan
Write-Host "插入顺序建议：先插 Follower（通常分到较小 COM 号），再插 Leader。"
Write-Host "USB 只负责通信，舵机必须另接 5V/12V 电源。`n"

$info = @(Get-SerialPortInfo)
if ($info.Count -eq 0) {
    Write-Bad "没有检测到任何 COM 口。"
    Write-Host "  排查：换一根【数据线】；装 CH340 / CP210x 驱动；换 USB 口（优先 USB 3.0、直连不用 Hub）。"
    exit 1
}

$info | Format-Table Port, Kind, DevicePath -AutoSize | Out-String -Width 200 | Write-Host

$usb = @($info | Where-Object { $_.Kind -eq 'USB' })
$bt  = @($info | Where-Object { $_.Kind -eq '蓝牙' })

Write-Host "USB 转串口（机械臂应该出现在这里）: $(if ($usb) { ($usb.Port -join ', ') } else { '（无）' })" -ForegroundColor Green
Write-Host "蓝牙虚拟串口（忽略）             : $(if ($bt) { ($bt.Port -join ', ') } else { '（无）' })"
Write-Host "`n常见 USB 转串口芯片："
Write-Host "  - USB-SERIAL CH340 / CH341      （Seeed 舵机驱动板常见）"
Write-Host "  - USB 串行设备 (COMx)"
Write-Host "  - Silicon Labs CP210x USB to UART Bridge`n"

if ($usb.Count -eq 2) {
    Write-Host "检测到 2 个 USB 转串口，按插入顺序推断：" -ForegroundColor Cyan
    Write-Host "  Follower = $($usb[0].Port)   Leader = $($usb[1].Port)"
    Write-Host "  一条命令写回配置：" -ForegroundColor Cyan
    Write-Host "    powershell -ExecutionPolicy Bypass -File scripts\01-find-port.ps1 -SetFollower $($usb[0].Port) -SetLeader $($usb[1].Port)"
} elseif ($usb.Count -eq 1) {
    Write-Warn2 "只看到 1 个 USB 转串口 —— 另一个臂还没插？"
} elseif ($usb.Count -gt 2) {
    Write-Warn2 "看到 $($usb.Count) 个 USB 转串口，请用 -Interactive 逐个插拔确认哪个是哪个"
} else {
    Write-Warn2 "没有 USB 转串口设备，机械臂还没插上"
}

if ($Interactive) {
    Write-Host "`n>>> 启动 lerobot-find-port（按提示拔掉 USB 再回车）" -ForegroundColor Yellow
    Invoke-Lerobot "lerobot-find-port" @()
}

Write-Host "`n>>> 当前配置：FollowerPort=$($Cfg.FollowerPort)  LeaderPort=$($Cfg.LeaderPort)"
Write-Host "    查到后运行：powershell -ExecutionPolicy Bypass -File scripts\01-find-port.ps1 -SetFollower COMx -SetLeader COMy"
