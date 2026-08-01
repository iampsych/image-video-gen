<#
    Stop ComfyUI and the deploy manager.

        powershell -ExecutionPolicy Bypass -File scripts\stop.ps1

    Asks the manager to stop ComfyUI, then shuts the manager down. The manager
    also stops ComfyUI on its own way out, so the first call is belt and braces
    - it just makes the ordering explicit and the output readable.
#>
[CmdletBinding()]
param(
    [string]$BindHost = "127.0.0.1",
    [int]$Port = 8500
)

$ErrorActionPreference = "Continue"
$uiHost = if ($BindHost -in @("0.0.0.0", "")) { "127.0.0.1" } else { $BindHost }
$managerUrl = "http://${uiHost}:${Port}"

Write-Host ""

try { $null = Invoke-RestMethod -Uri "$managerUrl/api/state" -TimeoutSec 3 }
catch {
    Write-Host "  [ok]   manager was not running at $managerUrl" -ForegroundColor DarkGray
    Write-Host ""
    exit 0
}

try {
    $null = Invoke-RestMethod -Uri "$managerUrl/api/comfy/stop" -Method Post `
                              -Body "{}" -ContentType "application/json" -TimeoutSec 30
    Write-Host "  [ok]   ComfyUI stopped" -ForegroundColor Green
} catch {
    Write-Host "  [warn] could not stop ComfyUI: $($_.Exception.Message)" -ForegroundColor Yellow
}

# /api/shutdown answers and then exits, so the connection drops mid-reply.
try {
    $null = Invoke-RestMethod -Uri "$managerUrl/api/shutdown" -Method Post `
                              -Body "{}" -ContentType "application/json" -TimeoutSec 5
} catch { }

Start-Sleep -Seconds 1
try {
    $null = Invoke-RestMethod -Uri "$managerUrl/api/state" -TimeoutSec 3
    Write-Host "  [warn] manager still responding - close its window manually" -ForegroundColor Yellow
} catch {
    Write-Host "  [ok]   manager stopped" -ForegroundColor Green
}

Write-Host ""
