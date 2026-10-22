param(
    [switch]$Lite,
    [switch]$NoFFmpeg,
    [switch]$SkipRuntime,
    [switch]$NoSmokeTest
)
$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root

function Step($msg) { Write-Host "`n== $msg" -ForegroundColor Yellow }
function Need($ok, $msg) { if (-not $ok) { throw $msg } }

$venvPy = Join-Path $Root ".venv\Scripts\python.exe"
Need (Test-Path $venvPy) "Run scripts\setup.ps1 first."
Need (Get-Command npm -ErrorAction SilentlyContinue) "The build needs Node.js. Install the LTS version from https://nodejs.org and open a new PowerShell window."

$Build = Join-Path $Root "build"
$Cache = Join-Path $Build "cache"
$Runtime = Join-Path $Build "runtime"
$PyDir = Join-Path $Runtime "python"
$Site = Join-Path $PyDir "Lib\site-packages"
$BundlePy = Join-Path $PyDir "python.exe"
New-Item -ItemType Directory -Force -Path $Cache | Out-Null

if (-not $SkipRuntime) {
    Step "Downloading the embeddable Python that matches .venv"
    $ver = (& $venvPy -c "import sys; print('%d.%d.%d' % sys.version_info[:3])").Trim()
    $p = $ver.Split(".")
    $tag = "$($p[0])$($p[1])"
    if (Test-Path $Runtime) { Remove-Item -Recurse -Force $Runtime }
    New-Item -ItemType Directory -Force -Path $PyDir | Out-Null
    $zip = $null
    for ($patch = [int]$p[2]; $patch -ge 0 -and -not $zip; $patch--) {
        $v = "$($p[0]).$($p[1]).$patch"
        $file = Join-Path $Cache "python-$v-embed-amd64.zip"
        if (-not (Test-Path $file)) {
            try {
                Invoke-WebRequest -UseBasicParsing -Uri "https://www.python.org/ftp/python/$v/python-$v-embed-amd64.zip" -OutFile $file
            } catch {
                Remove-Item -Force $file -ErrorAction SilentlyContinue
                continue
            }
        }
        $zip = $file
        Write-Host "Using the Python $v embeddable package"
    }
    Need $zip "Could not download an embeddable Python $($p[0]).$($p[1]) from python.org."
    Expand-Archive -Path $zip -DestinationPath $PyDir -Force
    $pth = Get-ChildItem -Path $PyDir -Filter "python*._pth" | Select-Object -First 1
    Need $pth "The embeddable Python has no ._pth file."
    Set-Content -Path $pth.FullName -Encoding Ascii -Value @("python$tag.zip", ".", "Lib\site-packages", "..\engine", "import site")

    Step "Installing the engine packages into the bundle (same versions as .venv)"
    New-Item -ItemType Directory -Force -Path $Site | Out-Null
    $constraints = Join-Path $Cache "constraints.txt"
    & $venvPy -m pip freeze --exclude-editable |
        Where-Object { $_ -notmatch "^(-e |pip==|setuptools==|wheel==)" -and $_ -notmatch " @ " } |
        Set-Content -Encoding Ascii -Path $constraints
    $reqs = @("-r", "engine\requirements.txt")
    if (-not $Lite) { $reqs += @("-r", "engine\requirements-ml.txt") }
    & $venvPy -m pip install --disable-pip-version-check --no-warn-script-location --target $Site -c $constraints @reqs
    Need ($LASTEXITCODE -eq 0) "pip could not install the engine packages."

    Step "Copying the engine and the UI"
    New-Item -ItemType Directory -Force -Path (Join-Path $Runtime "engine") | Out-Null
    Copy-Item -Recurse -Force (Join-Path $Root "engine\caa") (Join-Path $Runtime "engine\caa")
    Copy-Item -Recurse -Force (Join-Path $Root "ui") (Join-Path $Runtime "ui")
    Get-ChildItem -Path (Join-Path $Runtime "engine") -Recurse -Directory -Filter "__pycache__" | Remove-Item -Recurse -Force
    foreach ($dll in @("msvcp140.dll", "msvcp140_1.dll", "msvcp140_2.dll", "vcruntime140_1.dll", "concrt140.dll")) {
        $src = Join-Path $env:WINDIR "System32\$dll"
        if ((Test-Path $src) -and -not (Test-Path (Join-Path $PyDir $dll))) { Copy-Item $src $PyDir }
    }

    if (-not $NoFFmpeg) {
        Step "Bundling FFmpeg"
        $env:PYTHONPATH = Join-Path $Root "engine"
        $ff = (& $venvPy -c "from caa import media; print(media.ffmpeg_location() or '')").Trim()
        $env:PYTHONPATH = ""
        if ($ff -and (Test-Path $ff)) {
            $item = Get-Item $ff
            if ($item.LinkType -and $item.Target) {
                $t = @($item.Target)[0]
                if (-not [System.IO.Path]::IsPathRooted($t)) { $t = Join-Path (Split-Path -Parent $ff) $t }
                $ff = $t
            }
            $dir = Split-Path -Parent $ff
            $bin = Join-Path $Runtime "bin"
            New-Item -ItemType Directory -Force -Path $bin | Out-Null
            Copy-Item (Join-Path $dir "ffmpeg.exe") $bin
            Copy-Item (Join-Path $dir "ffprobe.exe") $bin
            Get-ChildItem -Path $dir -Filter "*.dll" | Copy-Item -Destination $bin
            Write-Host "Bundled FFmpeg from $dir"
        } else {
            Write-Host "FFmpeg not found, so it is not bundled. The app will ask the user to install it." -ForegroundColor DarkYellow
        }
    }

    Step "Checking the bundle"
    $env:PYTHONNOUSERSITE = "1"
    & $BundlePy -c "import caa.api, caa.services, numpy, cv2, uvicorn, starlette, watchdog, keyring, requests; print('engine imports OK')"
    Need ($LASTEXITCODE -eq 0) "The bundled Python could not import the engine."
    if (-not $Lite) {
        & $BundlePy -c "import torch, transformers, onnx_asr, onnxruntime; print('model runtimes OK, torch', torch.__version__)"
        Need ($LASTEXITCODE -eq 0) "The bundled Python could not import the model runtimes."
    }
    $size = (Get-ChildItem -Recurse -File $Runtime | Measure-Object -Property Length -Sum).Sum / 1MB
    Write-Host ("Bundle size: {0:N0} MB" -f $size)
}

Need (Test-Path $BundlePy) "No bundle in build\runtime. Run this script without -SkipRuntime."

if (-not $NoSmokeTest) {
    Step "Starting the bundled engine once"
    $smokeHome = Join-Path $Build "smoke-home"
    if (Test-Path $smokeHome) { Remove-Item -Recurse -Force $smokeHome }
    New-Item -ItemType Directory -Force -Path $smokeHome | Out-Null
    Set-Content -Encoding Ascii -Path (Join-Path $smokeHome "settings.json") -Value '{"asr_enabled": false, "embed_backend": "fallback", "semantic_search": false, "privacy_mode": "local"}'
    $oldHome = $env:CAA_HOME
    $oldMode = $env:CAA_PRIVACY_MODE
    $env:CAA_HOME = $smokeHome
    $env:CAA_PRIVACY_MODE = "local"
    $env:PYTHONNOUSERSITE = "1"
    $proc = Start-Process -FilePath $BundlePy -ArgumentList "-m caa serve --no-browser --port 8799" -WindowStyle Hidden -PassThru
    $ok = $false
    try {
        for ($i = 0; $i -lt 90 -and -not $ok; $i++) {
            Start-Sleep -Seconds 1
            if ($proc.HasExited) { break }
            try {
                $st = Invoke-RestMethod -Uri "http://127.0.0.1:8799/api/status" -TimeoutSec 2
                $page = Invoke-WebRequest -UseBasicParsing -Uri "http://127.0.0.1:8799/" -TimeoutSec 2
                if ($st.version -and $page.StatusCode -eq 200) { $ok = $true }
            } catch { }
        }
    } finally {
        if (-not $proc.HasExited) { Stop-Process -Id $proc.Id -Force }
        $env:CAA_HOME = $oldHome
        $env:CAA_PRIVACY_MODE = $oldMode
        Remove-Item -Recurse -Force $smokeHome -ErrorAction SilentlyContinue
    }
    Need $ok "The bundled engine did not start. Run build\runtime\python\python.exe -m caa serve to see the error."
    Write-Host "The bundled engine started and served the app."
}

Step "Building the Windows installer (this takes a few minutes)"
Push-Location (Join-Path $Root "electron")
try {
    npm install --no-audit --no-fund
    Need ($LASTEXITCODE -eq 0) "npm install failed."
    npm run dist
    if ($LASTEXITCODE -ne 0) {
        Write-Host "Retrying without editing the app's .exe resources. Turn on Windows Developer Mode (Settings > System > For developers) to give the .exe its own icon." -ForegroundColor DarkYellow
        npm run dist -- "-c.win.signAndEditExecutable=false"
        Need ($LASTEXITCODE -eq 0) "electron-builder failed. See the messages above."
    }
} finally {
    Pop-Location
}

$setup = Get-ChildItem -Path (Join-Path $Root "electron\dist") -Filter "CreatorAssetAssistant-Setup-*.exe" |
    Sort-Object LastWriteTime -Descending | Select-Object -First 1
Need $setup "The installer was not created."
$hash = (Get-FileHash -Algorithm SHA256 $setup.FullName).Hash
Set-Content -Path ($setup.FullName + ".sha256") -Encoding Ascii -Value "$hash  $($setup.Name)"
Write-Host "`nInstaller: $($setup.FullName)" -ForegroundColor Green
Write-Host ("Size: {0:N0} MB" -f ($setup.Length / 1MB))
Write-Host "SHA-256: $hash"
