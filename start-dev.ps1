param()

$ErrorActionPreference = "Stop"

$root = (Resolve-Path (Split-Path -Parent $MyInvocation.MyCommand.Path)).Path

if (-not (Test-Path "$root\frontend")) {
    Write-Error "Could not find frontend folder at: $root\frontend"
    exit 1
}

Start-Process powershell -ArgumentList @(
    "-NoExit",
    "-Command",
    "Set-Location '$root'; uv run uvicorn src.api.server:app --reload --host 0.0.0.0 --port 8000"
)

Start-Process powershell -ArgumentList @(
    "-NoExit",
    "-Command",
    "Set-Location '$root\frontend'; pnpm run dev"
)

Write-Host "Started backend and frontend in separate PowerShell windows."
