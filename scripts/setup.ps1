param(
    [switch]$NoModels,
    [switch]$Desktop
)
$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root

function Step($msg) { Write-Host "`n== $msg" -ForegroundColor Yellow }

Step "Python"
$pyExe = $null
$pyArgs = @()
if (Get-Command py -ErrorAction SilentlyContinue) { $pyExe = "py"; $pyArgs = @("-3") }
elseif (Get-Command python -ErrorAction SilentlyContinue) { $pyExe = "python" }
if (-not $pyExe) { throw "Python 3.10+ not found. Install it from https://www.python.org/downloads/ (tick 'Add to PATH')." }
& $pyExe @pyArgs -c "import sys; assert sys.version_info >= (3, 10), sys.version; print(sys.version)"

if (-not (Test-Path ".venv")) {
    Step "Creating virtual environment in .venv"
    & $pyExe @pyArgs -m venv .venv
}
$venvPy = Join-Path $Root ".venv\Scripts\python.exe"
& $venvPy -m pip install --upgrade pip | Out-Null

Step "Installing engine packages"
& $venvPy -m pip install -r engine\requirements.txt

if (-not $NoModels) {
    Step "Installing model runtimes (PyTorch CPU, Transformers, Parakeet ONNX). This is the big download."
    & $venvPy -m pip install -r engine\requirements-ml.txt
}
if ($Desktop) {
    Step "Installing desktop window + packager"
    & $venvPy -m pip install -r desktop\requirements.txt
}

Step "FFmpeg"
if (-not (Get-Command ffmpeg -ErrorAction SilentlyContinue)) {
    if (Get-Command winget -ErrorAction SilentlyContinue) {
        Write-Host "FFmpeg not found. Installing with winget (Gyan.FFmpeg)..."
        winget install --id Gyan.FFmpeg -e --accept-source-agreements --accept-package-agreements
        Write-Host "Close and reopen PowerShell so ffmpeg is on PATH, then run this script again." -ForegroundColor Cyan
    } else {
        Write-Host "FFmpeg not found. Download it from https://www.gyan.dev/ffmpeg/builds/ and add its bin folder to PATH." -ForegroundColor Red
    }
} else {
    ffmpeg -version | Select-Object -First 1
}

if (-not (Test-Path ".env")) {
    Copy-Item ".env.example" ".env"
    Write-Host "`nCreated .env. Put your NEBIUS_API_KEY (and later TAVILY_API_KEY) in it." -ForegroundColor Cyan
}

Step "Checking everything"
$env:PYTHONPATH = Join-Path $Root "engine"
& $venvPy -m caa doctor
Write-Host "`nDone. Start the app with: powershell -ExecutionPolicy Bypass -File scripts\run.ps1" -ForegroundColor Green
