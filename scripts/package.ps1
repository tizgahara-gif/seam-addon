$ErrorActionPreference = "Stop"

$AddonDir = "auto_seam_uv_equalizer"
$ZipName = "auto_seam_uv_equalizer.zip"

if (-not (Test-Path $AddonDir)) {
    throw "Addon folder not found: $AddonDir"
}

if (Test-Path $ZipName) {
    Remove-Item $ZipName -Force
}

Get-ChildItem -Recurse -Directory -Filter "__pycache__" | Remove-Item -Recurse -Force
Get-ChildItem -Recurse -File -Filter "*.pyc" | Remove-Item -Force

Compress-Archive -Path ".\$AddonDir" -DestinationPath ".\$ZipName" -Force

python .\scripts\verify_package.py ".\$ZipName"

Write-Host "Created $ZipName"
Write-Host "Expected structure:"
Write-Host "$ZipName/$AddonDir/__init__.py"
