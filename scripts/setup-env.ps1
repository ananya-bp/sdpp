# Creates .env from .env.example with freshly generated random secrets (Windows PowerShell 5.1+ / PowerShell 7).
# Usage (from the project root):  powershell -ExecutionPolicy Bypass -File scripts\setup-env.ps1
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$example = Join-Path $root ".env.example"
$target = Join-Path $root ".env"

if (Test-Path $target) {
    Write-Host ".env already exists - leaving it untouched. Delete it first if you want new secrets." -ForegroundColor Yellow
    exit 0
}

function New-HexSecret([int]$bytes) {
    $b = New-Object byte[] $bytes
    $rng = [System.Security.Cryptography.RandomNumberGenerator]::Create()
    $rng.GetBytes($b)
    $rng.Dispose()
    return -join ($b | ForEach-Object { $_.ToString("x2") })
}

$content = Get-Content $example -Raw
$content = $content -replace "POSTGRES_PASSWORD=.*", ("POSTGRES_PASSWORD=" + (New-HexSecret 16))
$content = $content -replace "SECRET_KEY=.*", ("SECRET_KEY=" + (New-HexSecret 32))
# Write without a BOM so Docker Compose reads the first variable name correctly.
[System.IO.File]::WriteAllText($target, $content, (New-Object System.Text.UTF8Encoding($false)))
Write-Host "Created .env with generated secrets. Next: docker compose up --build" -ForegroundColor Green
