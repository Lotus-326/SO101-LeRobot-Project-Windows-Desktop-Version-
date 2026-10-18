# ============================================================================
#  05 - 查找相机（OpenCV / Orbbec / RealSense）
#
#  用法:
#    powershell -ExecutionPolicy Bypass -File scripts\05-find-cameras.ps1
#    powershell -ExecutionPolicy Bypass -File scripts\05-find-cameras.ps1 -Backend opencv
#    powershell -ExecutionPolicy Bypass -File scripts\05-find-cameras.ps1 -Backend orbbec
#
#  输出内容:
#    - 每个相机的编号/序列号
#    - 默认分辨率与帧率
#    - 抓拍的样张，保存到 outputs\captured_images\
# ============================================================================
[CmdletBinding()]
param(
    [ValidateSet("all", "opencv", "orbbec", "realsense")]
    [string]$Backend = "all",
    [double]$RecordTimeS = 6.0
)

$ErrorActionPreference = "Stop"
. (Join-Path $PSScriptRoot "_common.ps1")
$Cfg = Import-LerobotConfig
Initialize-LerobotEnv

$argv = @()
if ($Backend -ne "all") { $argv += $Backend }
$argv += "--record-time-s=$RecordTimeS"
$argv += "--output-dir=outputs/captured_images"

Write-Host ">>> 查找相机 (backend=$Backend)" -ForegroundColor Cyan
Write-Host "提示：Orbbec 会同时暴露多个 OpenCV 编号，建议最后插入普通 USB 相机。" -ForegroundColor Yellow

Push-Location $script:RepoDir
try {
    Invoke-Lerobot "lerobot-find-cameras" $argv
}
finally { Pop-Location }

$shots = Join-Path $script:RepoDir "outputs\captured_images"
if (Test-Path $shots) {
    Write-Ok "样张目录: $shots"
    Get-ChildItem $shots -Filter *.png -ErrorAction SilentlyContinue | Select-Object Name, Length | Format-Table -AutoSize
}

Write-Host "`n>>> 把结果填到 scripts\config.ps1 的 Cameras，例如：" -ForegroundColor Cyan
Write-Host '    "{ front: {type: opencv, index_or_path: 0, width: 640, height: 480, fps: 30} }"'
Write-Host '    "{ orbbec_color: {type: orbbec_color, serial_number_or_name: ''CP9JA530003A'', width: 640, height: 480, fps: 30, color_mode: rgb, warmup_s: 1} }"'
