[CmdletBinding()]
param(
    [string]$ProjectRoot = (Split-Path -Parent $PSScriptRoot),
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

$ProjectRoot = (Resolve-Path $ProjectRoot).Path
Set-Location $ProjectRoot
Step "GYANVERSE PHASE 11 VALIDATION"
Write-Host "Project: $ProjectRoot"

if (-not (Test-Path ".\pyproject.toml")) { throw "pyproject.toml is missing." }
if (-not (Test-Path ".\phase11_core.py")) { throw "Phase 11 source files are missing." }

Step "Python syntax and packaging configuration"
@'
import ast, pathlib, tomllib
root = pathlib.Path.cwd()
for name in ("main.py", "gyanverse_ui.py", "gyanverse_ui_helpers.py", "phase11_core.py", "phase11_ai.py"):
    ast.parse((root / name).read_text(encoding="utf-8"), filename=name)
config = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))
assert config["tool"]["flet"]["android"]["min_sdk_version"] == 24
print("Syntax/configuration PASS")
'@ | python -
if ($LASTEXITCODE -ne 0) { throw "Syntax/configuration validation failed." }

Step "Automated regression"
python -m unittest discover -s tests
if ($LASTEXITCODE -ne 0) { throw "Unit tests failed." }

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
        throw "Runtime dependencies are missing. Run: python -m pip install -r requirements.txt"
    }
}

Step "Phase 11 validation PASS"
Write-Host "Expected prepared total: 215 tests." -ForegroundColor Green
Write-Host "Device/build acceptance remains pending until the EXE and APK are tested." -ForegroundColor Yellow
