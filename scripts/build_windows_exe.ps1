[CmdletBinding()]
param(
    [string]$ProjectRoot = (Split-Path -Parent $PSScriptRoot),
    [switch]$SkipTests
)
$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest
$env:PYTHONUTF8 = "1"
$env:PYTHONIOENCODING = "utf-8"
[Console]::InputEncoding = [System.Text.UTF8Encoding]::new($false)
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)

function Run-Flet([string[]]$Arguments) {
    $command = Get-Command flet -ErrorAction SilentlyContinue
    if ($command) { & $command.Source @Arguments }
    else { python -m flet @Arguments }
    if ($LASTEXITCODE -ne 0) { throw "Flet command failed: $($Arguments -join ' ')" }
}

$ProjectRoot = (Resolve-Path $ProjectRoot).Path
Set-Location $ProjectRoot
Write-Host "GYANVERSE PHASE 11 WINDOWS BUILD" -ForegroundColor Cyan
python -m pip install -r requirements.txt
if ($LASTEXITCODE -ne 0) { throw "Dependency installation failed." }
if (-not $SkipTests) { & "$PSScriptRoot\validate_phase11.ps1" -ProjectRoot $ProjectRoot }
$output = Join-Path $ProjectRoot "build\windows"
Run-Flet @("build", "windows", "--output", $output, "-v")
$exe = Get-ChildItem $output -Recurse -File -Filter *.exe | Sort-Object Length -Descending | Select-Object -First 1
if (-not $exe) { throw "Windows EXE was not found under $output" }
$hash = (Get-FileHash $exe.FullName -Algorithm SHA256).Hash
Write-Host "`nPHASE 11 WINDOWS EXE BUILD: PASS" -ForegroundColor Green
Write-Host "EXE: $($exe.FullName)"
Write-Host "SHA256: $hash"
Write-Host "Desktop workflow acceptance is still required." -ForegroundColor Yellow
