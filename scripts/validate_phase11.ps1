[CmdletBinding()]
param(
    [string]$ProjectRoot = "",
    [switch]$SkipDependencyCheck
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest
$env:PYTHONUTF8 = "1"
$env:PYTHONIOENCODING = "utf-8"
[Console]::InputEncoding = [System.Text.UTF8Encoding]::new($false)
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)

function Step([string]$Text) {
    Write-Host "`n============================================================" -ForegroundColor DarkCyan
    Write-Host $Text -ForegroundColor Cyan
    Write-Host "============================================================" -ForegroundColor DarkCyan
}

if ([string]::IsNullOrWhiteSpace($ProjectRoot)) {
    if (-not [string]::IsNullOrWhiteSpace($PSScriptRoot)) {
        $ProjectRoot = Split-Path -Parent $PSScriptRoot
    } else {
        $ProjectRoot = (Get-Location).Path
    }
}

if (-not (Test-Path $ProjectRoot)) {
    Write-Error "Invalid ProjectRoot directory: $ProjectRoot"
    exit 1
}

$ProjectRoot = (Resolve-Path $ProjectRoot).Path
Set-Location $ProjectRoot
Step "GYANVERSE PHASE 11 VALIDATION"
Write-Host "Project: $ProjectRoot"

if (-not (Test-Path ".\pyproject.toml")) {
    Write-Error "pyproject.toml is missing."
    exit 1
}
if (-not (Test-Path ".\phase11_core.py")) {
    Write-Error "Phase 11 source files are missing."
    exit 1
}

Step "Python syntax and packaging configuration"
@'
import ast, pathlib, sys, tomllib

root = pathlib.Path.cwd()
py_files = [
    p for p in root.glob("*.py")
    if not p.name.startswith((".", "_"))
]
if (root / "academy_core").exists():
    py_files.extend((root / "academy_core").glob("*.py"))
if (root / "scripts").exists():
    py_files.extend((root / "scripts").glob("*.py"))

for p in py_files:
    if any(ignored in str(p).lower() for ignored in ("backup", "safety", "historical", "_safety")):
        continue
    ast.parse(p.read_text(encoding="utf-8"), filename=str(p.relative_to(root)))

config = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))
assert config["tool"]["flet"]["android"]["min_sdk_version"] == 24
print("Syntax/configuration PASS")
'@ | python -
if ($LASTEXITCODE -ne 0) {
    Write-Error "Syntax/configuration validation failed."
    exit 1
}

Step "Automated regression"
$testOutput = python -c "import unittest, sys; suite = unittest.TestLoader().discover('tests'); runner = unittest.TextTestRunner(stream=sys.stdout, verbosity=1); res = runner.run(suite); print(f'DYNAMIC_TEST_COUNT:{res.testsRun}'); sys.exit(0 if res.wasSuccessful() else 1)"
if ($LASTEXITCODE -ne 0) {
    Write-Error "Unit tests failed."
    exit 1
}

$dynamicTestCount = 0
foreach ($line in ($testOutput -split "`r?`n")) {
    Write-Host $line
    if ($line -match "DYNAMIC_TEST_COUNT:(\d+)") {
        $dynamicTestCount = [int]$Matches[1]
    }
}

if (-not $SkipDependencyCheck) {
    Step "Runtime dependency import check"
    @'
import flet
import flet_audio
import flet_audio_recorder
from google import genai
print("Runtime dependency imports PASS")
'@ | python -
    if ($LASTEXITCODE -ne 0) {
        Write-Error "Runtime dependencies are missing. Run: python -m pip install -r requirements.txt"
        exit 1
    }
}

Step "Phase 11 validation PASS"
Write-Host "Automated regression: $dynamicTestCount tests passed dynamically." -ForegroundColor Green
Write-Host "Windows EXE, Android APK, and physical-device acceptance remain pending." -ForegroundColor Yellow
