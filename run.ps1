# Starts the household dashboard, reachable on the home WiFi network.
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

if (-not (Test-Path ".venv")) {
    python -m venv .venv
}

& ".venv\Scripts\python.exe" -m pip install -q -r requirements.txt

if (-not (Test-Path ".env")) {
    Copy-Item ".env.example" ".env"
    Write-Host "Created .env from .env.example - edit it to set a real HOUSEHOLD_PASSWORD before others connect."
}

Write-Host ""
Write-Host "Starting on http://0.0.0.0:8000 - find your LAN IP with 'ipconfig' to share with others on WiFi."
Write-Host "Windows may prompt to allow this through the firewall on first run - allow it for Private networks."
Write-Host ""

& ".venv\Scripts\python.exe" -m uvicorn app.main:app --host 0.0.0.0 --port 8000
