<#
    Bootstrap for a fresh Windows machine.

    Verifies Python, then starts the deploy manager. Everything else - cloning
    ComfyUI, building the venv, installing the right PyTorch, downloading models
    - happens in the web UI.

        powershell -ExecutionPolicy Bypass -File scripts\bootstrap.ps1
#>
[CmdletBinding()]
param(
    [string]$BindHost = "127.0.0.1",
    [int]$Port = 8500,
    [switch]$NoBrowser
)

$ErrorActionPreference = "Stop"
$repo = Split-Path -Parent $PSScriptRoot
Set-Location $repo

Write-Host ""
Write-Host "  ComfyUI Deploy - bootstrap" -ForegroundColor Cyan
Write-Host "  $repo"
Write-Host ""

# --- Python ---------------------------------------------------------------

$python = $null
foreach ($candidate in @("python", "py")) {
    $cmd = Get-Command $candidate -ErrorAction SilentlyContinue
    if (-not $cmd) { continue }
    try { $version = & $candidate -c "import sys;print('%d.%d' % sys.version_info[:2])" 2>$null }
    catch { continue }
    if ($version -and [version]$version -ge [version]"3.9") {
        $python = $candidate
        Write-Host "  [ok]   Python $version  ($($cmd.Source))" -ForegroundColor Green
        break
    }
}

if (-not $python) {
    Write-Host "  [FAIL] Python 3.9+ not found on PATH." -ForegroundColor Red
    Write-Host "         Install it from https://www.python.org/downloads/ and tick"
    Write-Host "         'Add python.exe to PATH', then re-run this script."
    exit 1
}

# --- git ------------------------------------------------------------------

if (Get-Command git -ErrorAction SilentlyContinue) {
    Write-Host "  [ok]   git available" -ForegroundColor Green
} else {
    Write-Host "  [warn] git not found - the manager cannot clone ComfyUI without it." -ForegroundColor Yellow
    Write-Host "         Install from https://git-scm.com/download/win"
}

# --- GPU ------------------------------------------------------------------

if (Get-Command nvidia-smi -ErrorAction SilentlyContinue) {
    $gpu = (& nvidia-smi --query-gpu=name,memory.total --format=csv,noheader) | Select-Object -First 1
    Write-Host "  [ok]   GPU: $gpu" -ForegroundColor Green
} else {
    Write-Host "  [warn] nvidia-smi not found - no NVIDIA driver detected." -ForegroundColor Yellow
}

# --- firewall hint --------------------------------------------------------

if ($BindHost -eq "0.0.0.0") {
    Write-Host ""
    Write-Host "  Binding to 0.0.0.0. If another machine cannot reach it, allow the port:" -ForegroundColor Yellow
    Write-Host "    New-NetFirewallRule -DisplayName 'ComfyUI Deploy' -Direction Inbound ``"
    Write-Host "      -LocalPort $Port,8188 -Protocol TCP -Action Allow"
}

# --- launch ---------------------------------------------------------------

Write-Host ""
$launchArgs = @("manage.py", "--host", $BindHost, "--port", $Port)
if ($NoBrowser) { $launchArgs += "--no-browser" }
& $python $launchArgs
