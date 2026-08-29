[CmdletBinding()]
param(
    [string]$ProjectRoot = (Split-Path -Parent $PSScriptRoot),
    [switch]$SkipTests
)
$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest
$env:PYTHONUTF8 = "1"
$env:PYTHONIOENCODING = "utf-8"
$env:JAVA_TOOL_OPTIONS = "-Dfile.encoding=UTF-8"
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
Write-Host "GYANVERSE PHASE 11 ANDROID BUILD" -ForegroundColor Cyan
Write-Host "Project: $ProjectRoot"

python -m pip install -r requirements.txt
if ($LASTEXITCODE -ne 0) { throw "Dependency installation failed." }
if (-not $SkipTests) { & "$PSScriptRoot\validate_phase11.ps1" -ProjectRoot $ProjectRoot }

@'
import pathlib, tomllib
config = tomllib.loads(pathlib.Path("pyproject.toml").read_text(encoding="utf-8"))
assert config["tool"]["flet"]["android"]["min_sdk_version"] == 24
print("Android minSdkVersion 24 PASS")
'@ | python -
if ($LASTEXITCODE -ne 0) { throw "Android minimum SDK gate failed." }

$flutterCache = Join-Path $ProjectRoot "build\flutter"
if (Test-Path $flutterCache) {
    Write-Host "Removing stale generated Flutter cache: $flutterCache" -ForegroundColor Yellow
    Remove-Item $flutterCache -Recurse -Force
}
$output = Join-Path $ProjectRoot "build\apk"
Run-Flet @("build", "apk", "--output", $output, "-v")
$apk = Get-ChildItem $output -Recurse -File -Filter *.apk | Sort-Object Length -Descending | Select-Object -First 1
if (-not $apk) { throw "APK was not found under $output" }
$canonical = Join-Path $output "GyanVerse_Academy.apk"
if ($apk.FullName -ne $canonical) { Copy-Item $apk.FullName $canonical -Force }
$hash = (Get-FileHash $canonical -Algorithm SHA256).Hash
Write-Host "`nPHASE 11 ANDROID APK BUILD: PASS" -ForegroundColor Green
Write-Host "APK: $canonical"
Write-Host "Size MB: $([math]::Round((Get-Item $canonical).Length / 1MB, 2))"
Write-Host "SHA256: $hash"
Write-Host "Real-device voice, attachment and layout acceptance is still required." -ForegroundColor Yellow
