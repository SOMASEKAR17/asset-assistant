$ErrorActionPreference = 'Stop'
$repo = Split-Path -Parent $PSScriptRoot
$vendor = Join-Path $PSScriptRoot 'vendor'
# Only this generated directory may be replaced. Never mutate desktop sources.
$expected = [IO.Path]::GetFullPath((Join-Path $repo 'deployment\vendor'))
if ([IO.Path]::GetFullPath($vendor) -ne $expected) { throw 'Unexpected snapshot directory' }
if (Test-Path -LiteralPath $vendor) { Remove-Item -LiteralPath $vendor -Recurse -Force }
New-Item -ItemType Directory -Force -Path "$vendor/engine", "$PSScriptRoot/site/fonts", "$PSScriptRoot/library", "$PSScriptRoot/seed" | Out-Null
Copy-Item -LiteralPath "$repo/engine/caa" -Destination "$vendor/engine/caa" -Recurse
Copy-Item -LiteralPath "$repo/engine/requirements.txt" -Destination "$vendor/requirements.txt"
Copy-Item -LiteralPath "$repo/engine/requirements-ml.txt" -Destination "$vendor/requirements-ml.txt"
Copy-Item -LiteralPath "$repo/ui/fonts/asset-display.ttf" -Destination "$PSScriptRoot/site/fonts/asset-display.ttf"
Copy-Item -LiteralPath "$repo/LICENSE" -Destination "$vendor/LICENSE"
Get-ChildItem -LiteralPath "$vendor/engine/caa" -File -Filter '*.py' | Get-FileHash -Algorithm SHA256 |
    Select-Object @{Name='File';Expression={Split-Path -Leaf $_.Path}},Hash |
    ConvertTo-Json | Set-Content -Encoding UTF8 "$vendor/source-hashes.json"
Write-Host 'Snapshot ready. Desktop source files were read only.'
