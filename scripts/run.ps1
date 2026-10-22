$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
$venvPy = Join-Path $Root ".venv\Scripts\python.exe"
if (-not (Test-Path $venvPy)) { throw "Run scripts\setup.ps1 first." }
$env:PYTHONPATH = Join-Path $Root "engine"
Set-Location $Root
if ($args.Count -gt 0 -and ($args[0] -eq "-App" -or $args[0] -eq "-Desktop")) {
    if (-not (Get-Command npm -ErrorAction SilentlyContinue)) { throw "The desktop app needs Node.js. Install the LTS version from https://nodejs.org and open a new PowerShell window." }
    Push-Location (Join-Path $Root "electron")
    try {
        if (-not (Test-Path "node_modules\electron")) {
            Write-Host "Installing Electron (first run only)..." -ForegroundColor Yellow
            npm install
            if ($LASTEXITCODE -ne 0) { throw "npm install failed. If GitHub downloads are blocked, set `$env:ELECTRON_MIRROR = 'https://npmmirror.com/mirrors/electron/' and try again." }
        }
        npm start
    } finally {
        Pop-Location
    }
} elseif ($args.Count -gt 0) {
    & $venvPy -m caa @args
} else {
    & $venvPy -m caa serve
}
exit $LASTEXITCODE
