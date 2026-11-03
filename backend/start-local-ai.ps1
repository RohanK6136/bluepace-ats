[CmdletBinding()]
param()

$ErrorActionPreference = "Stop"
$BackendDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$VenvPython = Join-Path $BackendDir ".venv\Scripts\python.exe"
$ModelName = "qwen3:8b"

Push-Location $BackendDir
try {
    if (-not (Get-Command ollama -ErrorAction SilentlyContinue)) {
        throw "Ollama is not installed. Install it from https://ollama.com/download/windows, then rerun this script."
    }

    try {
        $null = Invoke-RestMethod -Uri "http://127.0.0.1:11434/api/tags" -TimeoutSec 4
    }
    catch {
        throw "Ollama is installed but its local API is not responding. Open the Ollama app, or run 'ollama serve' in another terminal, then rerun this script."
    }

    $modelList = (& ollama list 2>&1 | Out-String)
    if ($LASTEXITCODE -ne 0) {
        throw "Could not list local Ollama models. Check that the Ollama service is running."
    }
    if ($modelList -notmatch "(?m)^$([regex]::Escape($ModelName))(\s|$)") {
        Write-Host "Downloading $ModelName to this computer (about 5.2 GB)..." -ForegroundColor Cyan
        & ollama pull $ModelName
        if ($LASTEXITCODE -ne 0) {
            throw "Ollama could not download $ModelName. Check disk space and network access, then retry."
        }
    }

    if (-not (Test-Path $VenvPython)) {
        Write-Host "Creating the local AI Python environment..." -ForegroundColor Cyan
        & python -m venv (Join-Path $BackendDir ".venv")
        if ($LASTEXITCODE -ne 0) {
            throw "Python virtual environment creation failed. Install Python 3.11 or newer and try again."
        }
    }

    Write-Host "Checking local AI dependencies..." -ForegroundColor Cyan
    & $VenvPython -m pip install -r requirements-local-ai.txt
    if ($LASTEXITCODE -ne 0) {
        throw "Local AI dependencies could not be installed."
    }

    # These settings affect only this local AI process. No provider key or credits are used.
    $env:APP_ENV = "development"
    $env:LLM_PROFILE = "local-ollama"
    $env:OLLAMA_BASE_URL = "http://127.0.0.1:11434/v1"
    $env:OLLAMA_MODEL = $ModelName
    $env:DB_PATH = ":memory:"
    $env:STORE_PAYLOADS = "false"
    $env:API_KEYS = ""

    Write-Host ""
    Write-Host "BluePace local AI is starting at http://127.0.0.1:8000" -ForegroundColor Green
    Write-Host "Keep this PowerShell window open while using JD & Applicant Match." -ForegroundColor Yellow
    Write-Host "Press Ctrl+C to stop the local AI service." -ForegroundColor Yellow
    & $VenvPython -m uvicorn local_ai_server:app --host 127.0.0.1 --port 8000
}
finally {
    Pop-Location
}
