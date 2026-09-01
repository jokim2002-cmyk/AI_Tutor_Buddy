[CmdletBinding()]
param(
    [string]$ProjectRoot = "",
    [switch]$SkipTests
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$env:PYTHONUTF8 = "1"
$env:PYTHONIOENCODING = "utf-8"

[Console]::InputEncoding = [System.Text.UTF8Encoding]::new($false)
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)

$scriptPath = $MyInvocation.MyCommand.Path

if ([string]::IsNullOrWhiteSpace($scriptPath)) {
    throw "Unable to resolve build script path."
}

$scriptRoot = Split-Path -Parent $scriptPath

if ([string]::IsNullOrWhiteSpace($ProjectRoot)) {
    $ProjectRoot = Split-Path -Parent $scriptRoot
}

function Run-Flet([string[]]$Arguments) {
    $command = Get-Command flet -ErrorAction SilentlyContinue

    if ($command) {
        & $command.Source @Arguments
    }
    else {
        python -m flet @Arguments
    }

    if ($LASTEXITCODE -ne 0) {
        throw "Flet command failed: $($Arguments -join ' ')"
    }
}

$ProjectRoot = (Resolve-Path $ProjectRoot).Path
Set-Location $ProjectRoot

Write-Host "GYANVERSE PHASE 11 WINDOWS BUILD" -ForegroundColor Cyan
Write-Host "Project root: $ProjectRoot"
Write-Host "Script root : $scriptRoot"

python -m pip install -r requirements.txt

if ($LASTEXITCODE -ne 0) {
    throw "Dependency installation failed."
}

if (-not $SkipTests) {
    & (Join-Path $scriptRoot "validate_phase11.ps1") `
        -ProjectRoot $ProjectRoot

    if ($LASTEXITCODE -ne 0) {
        throw "Phase 11 validation failed."
    }
}

$output = Join-Path $ProjectRoot "build\windows"

Run-Flet @(
    "build",
    "windows",
    "--output",
    $output,
    "-v"
)

$exe = Get-ChildItem $output `
    -Recurse `
    -File `
    -Filter *.exe |
    Sort-Object Length -Descending |
    Select-Object -First 1

if (-not $exe) {
    throw "Windows EXE was not found under $output"
}

$hash = (Get-FileHash $exe.FullName -Algorithm SHA256).Hash

Write-Host ""
Write-Host "PHASE 11 WINDOWS EXE BUILD: PASS" -ForegroundColor Green
Write-Host "EXE: $($exe.FullName)"
Write-Host "SIZE: $($exe.Length)"
Write-Host "SHA256: $hash"
Write-Host "Desktop workflow acceptance is still required." -ForegroundColor Yellow
