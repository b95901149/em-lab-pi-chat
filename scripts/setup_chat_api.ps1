# Setup THz Lab PI Chat API (Cloudflare Worker + GitHub Pages secret)
# Usage:
#   powershell -ExecutionPolicy Bypass -File scripts/setup_chat_api.ps1
#   powershell -ExecutionPolicy Bypass -File scripts/setup_chat_api.ps1 -SkipDeploy

param(
    [string]$WorkerName = "em-lab-pi-chat",
    [string]$PagesOrigin = "https://b95901149.github.io",
    [string]$GroqApiKey = "",
    [switch]$SkipDeploy
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
$WorkerDir = Join-Path $Root "worker"
$Python = if ($env:PYTHON) { $env:PYTHON } else { "C:\ProgramData\anaconda3\python.exe" }

function Write-Step($msg) { Write-Host "`n==> $msg" -ForegroundColor Cyan }

$WorkerUrl = "https://$WorkerName.workers.dev/v1/chat"
$HealthUrl = "https://$WorkerName.workers.dev/health"

Write-Step "Worker URL: $WorkerUrl"

if (-not $SkipDeploy) {
    Push-Location $WorkerDir
    try {
        Write-Step "Cloudflare login (browser) if needed"
        npx wrangler whoami 2>$null
        if ($LASTEXITCODE -ne 0) {
            npx wrangler login
        }

        if ($GroqApiKey) {
            Write-Step "Setting GROQ_API_KEY secret"
            $GroqApiKey | npx wrangler secret put GROQ_API_KEY
        } elseif (-not (Test-Path ".dev.vars")) {
            Write-Warning "No GROQ_API_KEY provided. Set via: npx wrangler secret put GROQ_API_KEY"
        }

        Write-Step "Deploying Worker"
        npx wrangler deploy
    } finally {
        Pop-Location
    }
}

Write-Step "Setting GitHub secret CHAT_API_URL"
gh secret set CHAT_API_URL --body $WorkerUrl

Write-Step "Triggering GitHub Pages deploy"
gh workflow run "Deploy Chat to GitHub Pages"
Start-Sleep -Seconds 3
$runId = (gh run list --workflow "Deploy Chat to GitHub Pages" --limit 1 --json databaseId -q ".[0].databaseId")
if ($runId) {
    Write-Host "Watching run $runId ..."
    gh run watch $runId --exit-status
}

Write-Step "Local build with production API URL"
& $Python (Join-Path $Root "scripts\build_web_chat.py") --lite-prompt --no-rag --api-url $WorkerUrl

Write-Step "Health check"
try {
    $health = Invoke-RestMethod -Uri $HealthUrl -TimeoutSec 15
    Write-Host "Worker health: $($health | ConvertTo-Json -Compress)" -ForegroundColor Green
} catch {
    Write-Warning "Worker health check failed: $_"
    Write-Warning "If 503, run: cd worker; npx wrangler secret put GROQ_API_KEY"
}

Write-Host "`nDone. Pages: https://b95901149.github.io/em-lab-pi-chat/" -ForegroundColor Green
