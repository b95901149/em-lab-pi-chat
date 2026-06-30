# 本機一鍵預覽（需先設定 worker/.dev.vars 的 GEMINI_API_KEY）

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
$NodeDir = "C:\Program Files\nodejs"
$env:Path = "$NodeDir;" + $env:Path

if (-not (Test-Path "$NodeDir\node.exe")) {
    Write-Host "找不到 Node.js。請安裝: winget install OpenJS.NodeJS.LTS --source winget" -ForegroundColor Red
    exit 1
}

Write-Host "Node $(node --version) / npm $(npm --version)"

if (-not (Test-Path "$Root\worker\.dev.vars")) {
    Write-Host ""
    Write-Host "請先建立 worker\.dev.vars（可複製 .dev.vars.example 並填入 GEMINI_API_KEY）" -ForegroundColor Yellow
    Write-Host "  https://aistudio.google.com/apikey" -ForegroundColor Yellow
    if (-not (Test-Path "$Root\worker\.dev.vars.example")) { exit 1 }
    Copy-Item "$Root\worker\.dev.vars.example" "$Root\worker\.dev.vars"
    Write-Host "已建立 worker\.dev.vars — 請編輯後再執行本腳本。" -ForegroundColor Yellow
    exit 1
}

Set-Location $Root
& "C:\ProgramData\anaconda3\python.exe" scripts/build_web_chat.py --lite-prompt --no-rag --api-url "http://127.0.0.1:8787/v1/chat"

Write-Host ""
Write-Host "啟動中…" -ForegroundColor Cyan
Write-Host "  前端: http://127.0.0.1:8769/" -ForegroundColor Green
Write-Host "  API:  http://127.0.0.1:8787/v1/chat" -ForegroundColor Green
Write-Host "  三思: http://127.0.0.1:8769/?sansha=1" -ForegroundColor Green
Write-Host "  Ctrl+C 停止" -ForegroundColor Gray
Write-Host ""

$pyJob = Start-Job {
    Set-Location $using:Root
    & "C:\ProgramData\anaconda3\python.exe" scripts/serve_docs.py --port 8769
}

Set-Location "$Root\worker"
try {
    npx wrangler dev --port 8787 --ip 127.0.0.1
} finally {
    Stop-Job $pyJob -ErrorAction SilentlyContinue
    Remove-Job $pyJob -Force -ErrorAction SilentlyContinue
}
