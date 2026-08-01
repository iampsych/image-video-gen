<#
    Start both the deploy manager and ComfyUI.

        powershell -ExecutionPolicy Bypass -File scripts\start.ps1

    The manager is launched first, then asked - through its own API - to start
    ComfyUI. That way the manager owns the ComfyUI process: its Launch tab shows
    the live log, its Stop button works, and quitting the manager takes ComfyUI
    down with it. Starting ComfyUI separately here would give you two owners and
    a fight over the port.

    Options:
      -BindHost 0.0.0.0   reachable from other machines on the LAN
      -Port 8500          manager port
      -ManagerOnly        skip starting ComfyUI
      -NoBrowser          don't open any tabs
#>
[CmdletBinding()]
param(
    [string]$BindHost = "127.0.0.1",
    [int]$Port = 8500,
    [switch]$ManagerOnly,
    [switch]$NoBrowser
)

$ErrorActionPreference = "Stop"
$repo = Split-Path -Parent $PSScriptRoot
Set-Location $repo

$uiHost = if ($BindHost -in @("0.0.0.0", "")) { "127.0.0.1" } else { $BindHost }
$managerUrl = "http://${uiHost}:${Port}"

function Test-Manager {
    try { $null = Invoke-RestMethod -Uri "$managerUrl/api/state" -TimeoutSec 3; return $true }
    catch { return $false }
}

Write-Host ""
Write-Host "  ComfyUI Deploy - start" -ForegroundColor Cyan
Write-Host "  $repo"
Write-Host ""

# --- manager ---------------------------------------------------------------

if (Test-Manager) {
    Write-Host "  [ok]   manager already running at $managerUrl" -ForegroundColor Green
} else {
    $python = $null
    foreach ($candidate in @("python", "py")) {
        $cmd = Get-Command $candidate -ErrorAction SilentlyContinue
        if (-not $cmd) { continue }
        try { $v = & $candidate -c "import sys;print('%d.%d' % sys.version_info[:2])" 2>$null } catch { continue }
        if ($v -and [version]$v -ge [version]"3.9") { $python = $candidate; break }
    }
    if (-not $python) {
        Write-Host "  [FAIL] Python 3.9+ not found on PATH." -ForegroundColor Red
        Write-Host "         Install from https://www.python.org/downloads/ with 'Add python.exe to PATH'."
        exit 1
    }

    Write-Host "  ...    starting manager" -ForegroundColor DarkGray
    $launchArgs = @("manage.py", "--host", $BindHost, "--port", $Port, "--no-browser")
    Start-Process -FilePath $python -ArgumentList $launchArgs -WorkingDirectory $repo | Out-Null

    $ready = $false
    foreach ($i in 1..40) {
        Start-Sleep -Milliseconds 500
        if (Test-Manager) { $ready = $true; break }
    }
    if (-not $ready) {
        Write-Host "  [FAIL] manager did not come up on $managerUrl" -ForegroundColor Red
        Write-Host "         Try: $python manage.py --doctor"
        exit 1
    }
    Write-Host "  [ok]   manager at $managerUrl" -ForegroundColor Green
}

# --- ComfyUI ---------------------------------------------------------------

if ($ManagerOnly) {
    Write-Host "  [skip] ComfyUI (-ManagerOnly)" -ForegroundColor Yellow
} else {
    $state = Invoke-RestMethod -Uri "$managerUrl/api/state" -TimeoutSec 10
    if ($state.comfy.running) {
        Write-Host "  [ok]   ComfyUI already running at $($state.comfy.url)" -ForegroundColor Green
        $comfyUrl = $state.comfy.url
    } else {
        Write-Host "  ...    starting ComfyUI" -ForegroundColor DarkGray
        $r = Invoke-RestMethod -Uri "$managerUrl/api/comfy/start" -Method Post `
                               -Body "{}" -ContentType "application/json" -TimeoutSec 30
        if (-not $r.ok) {
            Write-Host "  [FAIL] $($r.error)" -ForegroundColor Red
            Write-Host "         Check the Setup tab - the venv or requirements may be missing."
            exit 1
        }
        $comfyUrl = $r.url
        # the manager reports the url with a trailing slash; doubling it 404s
        $probe = $comfyUrl.TrimEnd('/')

        # ComfyUI takes a while to import torch and scan models
        $up = $false
        foreach ($i in 1..90) {
            Start-Sleep -Seconds 1
            try { $null = Invoke-RestMethod -Uri "$probe/api/system_stats" -TimeoutSec 2; $up = $true; break }
            catch { }
            $s = Invoke-RestMethod -Uri "$managerUrl/api/state" -TimeoutSec 5
            if (-not $s.comfy.running) {
                Write-Host "  [FAIL] ComfyUI exited during startup. Last lines:" -ForegroundColor Red
                $s.comfy.lines | Select-Object -Last 12 | ForEach-Object { Write-Host "         $_" }
                exit 1
            }
        }
        if ($up) { Write-Host "  [ok]   ComfyUI at $comfyUrl" -ForegroundColor Green }
        else     { Write-Host "  [warn] ComfyUI still starting - watch the Launch tab" -ForegroundColor Yellow }
    }
}

# --- done ------------------------------------------------------------------

Write-Host ""
Write-Host "  manager  $managerUrl"
if (-not $ManagerOnly -and $comfyUrl) { Write-Host "  ComfyUI  $comfyUrl" }
Write-Host ""
Write-Host "  Stop both with:  powershell -ExecutionPolicy Bypass -File scripts\stop.ps1" -ForegroundColor DarkGray
Write-Host ""

if (-not $NoBrowser) {
    if ($comfyUrl) { Start-Process $comfyUrl } else { Start-Process $managerUrl }
}
