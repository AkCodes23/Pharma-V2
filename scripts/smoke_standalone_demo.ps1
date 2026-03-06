param(
    [string]$Query = "Assess 2027 generic launch for Keytruda in India"
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

if (-not (Test-Path ".env")) {
    Copy-Item ".env.demo" ".env"
}

Write-Host "[smoke] Starting standalone demo stack..."
docker compose up -d --build | Out-Host

function Wait-Healthy {
    param(
        [Parameter(Mandatory=$true)][string]$Name,
        [Parameter(Mandatory=$true)][string]$Url,
        [int]$Attempts = 60
    )

    for ($i = 0; $i -lt $Attempts; $i++) {
        try {
            $resp = Invoke-RestMethod -Method Get -Uri $Url -TimeoutSec 3
            if ($resp.status -eq "healthy") {
                Write-Host "[smoke] $Name healthy"
                return
            }
        } catch {
            Start-Sleep -Seconds 2
        }
        Start-Sleep -Seconds 1
    }

    throw "[smoke] Timed out waiting for $Name health endpoint: $Url"
}

Wait-Healthy -Name "planner" -Url "http://localhost:8000/health"
Wait-Healthy -Name "supervisor" -Url "http://localhost:8001/health"
Wait-Healthy -Name "executor" -Url "http://localhost:8002/health"

$createHeaders = @{
    "Content-Type" = "application/json"
    "X-Demo-User" = "demo-user"
}
$createBody = @{ query = $Query } | ConvertTo-Json

Write-Host "[smoke] Creating demo session..."
$create = Invoke-RestMethod -Method Post -Uri "http://localhost:8000/api/v1/sessions" -Headers $createHeaders -Body $createBody
$sessionId = $create.session_id
if (-not $sessionId) {
    throw "[smoke] Session creation did not return session_id"
}
Write-Host "[smoke] Session: $sessionId"

$getHeaders = @{ "X-Demo-User" = "demo-user" }
$status = ""
$session = $null
for ($i = 0; $i -lt 120; $i++) {
    Start-Sleep -Seconds 2
    $session = Invoke-RestMethod -Method Get -Uri "http://localhost:8000/api/v1/sessions/$sessionId" -Headers $getHeaders
    $status = $session.status
    Write-Host "[smoke] status=$status"

    if ($status -eq "COMPLETED") {
        break
    }

    if ($status -eq "FAILED") {
        throw "[smoke] Session failed"
    }
}

if ($status -ne "COMPLETED") {
    throw "[smoke] Session did not reach COMPLETED"
}

if (-not $session.report_url) {
    throw "[smoke] Completed session missing report_url"
}

Write-Host "[smoke] Report URL: $($session.report_url)"
$download = Invoke-WebRequest -Uri $session.report_url -TimeoutSec 10
if ($download.StatusCode -lt 200 -or $download.StatusCode -ge 300) {
    throw "[smoke] Report URL is not downloadable"
}

$logs = docker compose logs --no-color
if ($logs -match "azure\.com|windows\.net|servicebus\.windows\.net") {
    throw "[smoke] Azure domain detected in runtime logs"
}

Write-Host "[smoke] PASS: standalone demo workflow completed without Azure egress markers."
