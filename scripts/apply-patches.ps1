# ============================================================================
#  apply-patches - 把 patches\*.patch 打到 lerobot 仓库上
#
#  用法:
#    powershell -ExecutionPolicy Bypass -File scripts\apply-patches.ps1
#    powershell -ExecutionPolicy Bypass -File scripts\apply-patches.ps1 -Check   # 只检查不落盘
#
#  背景:
#    Seeed 的 DepthCameraSupport 分支是从上游快照拼出来的，存在个别不一致。
#    本目录把这些必要修补固化成 .patch 文件，方便重装环境后一键复现。
#    重新 clone 仓库后请务必跑一次本脚本。
# ============================================================================
[CmdletBinding()]
param([switch]$Check)

$ErrorActionPreference = "Stop"
. (Join-Path $PSScriptRoot "_common.ps1")
$Cfg = Import-LerobotConfig

$patchDir = Join-Path $script:RootDir "patches"
if (-not (Test-Path $patchDir)) { Write-Warn2 "没有 patches 目录，跳过"; exit 0 }

$patches = Get-ChildItem $patchDir -Filter *.patch | Sort-Object Name
if (-not $patches) { Write-Warn2 "patches 目录为空，跳过"; exit 0 }

Write-Host ">>> 目标仓库: $script:RepoDir" -ForegroundColor Cyan
Write-Host "    分支: $(git -C $script:RepoDir branch --show-current)`n"

foreach ($p in $patches) {
    Write-Host "--- $($p.Name) ---" -ForegroundColor Yellow
    # ⚠️ git apply 失败时把信息写到 stderr；本脚本开头设了
    #    $ErrorActionPreference = "Stop"，PowerShell 会把原生程序的 stderr
    #    当成终止性错误 —— 脚本会当场中断，根本走不到下面的友好提示。
    #    所以这里临时放宽（与 _common.ps1 里 Invoke-Lerobot 的做法一致）。
    $prev = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    try {
        if ($Check) {
            $out = git -C $script:RepoDir apply --check $p.FullName 2>&1
            if ($LASTEXITCODE -eq 0) { Write-Ok "可应用" }
            else { Write-Warn2 "不可应用:"; $out | ForEach-Object { "    $_" } }
        } else {
            $out = git -C $script:RepoDir apply $p.FullName 2>&1
            if ($LASTEXITCODE -eq 0) {
                Write-Ok "已应用"
            } else {
                # 区分「已经打过」和「真的失败」：
                # 反向能干净应用 = 补丁内容已经在源码里了，属于正常情况。
                $null = git -C $script:RepoDir apply --check --reverse $p.FullName 2>&1
                if ($LASTEXITCODE -eq 0) {
                    Write-Ok "已应用过（源码已包含该修补，跳过）"
                } else {
                    Write-Warn2 "应用失败:"
                    $out | ForEach-Object { "    $_" }
                }
            }
        }
    }
    finally { $ErrorActionPreference = $prev }
}

Write-Host "`n>>> 当前仓库改动:" -ForegroundColor Cyan
git -C $script:RepoDir status --porcelain
