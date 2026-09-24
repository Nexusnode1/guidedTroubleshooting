# Starts the API and the chat UI in two windows, then opens the browser.
# Usage (from the project root):  .\scripts\dev.ps1
$root = Split-Path -Parent $PSScriptRoot

Start-Process powershell -ArgumentList "-NoExit", "-Command", "Set-Location '$root'; .\.venv\Scripts\python -m uvicorn app.main:app --port 8000"
Start-Process powershell -ArgumentList "-NoExit", "-Command", "Set-Location '$root\frontend'; npm run dev"

Write-Host "Waiting for the API to load the embedding model..."
$ready = $false
for ($i = 0; $i -lt 90 -and -not $ready; $i++) {
    Start-Sleep -Seconds 2
    try { $ready = (Invoke-WebRequest -Uri "http://localhost:8000/health" -UseBasicParsing -TimeoutSec 2).StatusCode -eq 200 } catch { }
}
if ($ready) { Start-Process "http://localhost:5173" } else { Write-Host "The API did not become ready; check the API window for errors." }
