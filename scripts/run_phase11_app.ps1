[CmdletBinding()]
param([string]$ProjectRoot)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

if ([string]::IsNullOrWhiteSpace($ProjectRoot)) {
    $scriptFile = $MyInvocation.MyCommand.Path
    if (-not [string]::IsNullOrWhiteSpace($scriptFile)) {
        $ProjectRoot = Split-Path -Parent (Split-Path -Parent $scriptFile)
    }
    else {
        $ProjectRoot = (Get-Location).Path
    }
}

$root = (Resolve-Path -LiteralPath $ProjectRoot).Path
$launcher = Join-Path $root "scripts\launch_gyanverse_hidden.pyw"
if (-not (Test-Path -LiteralPath $launcher -PathType Leaf)) {
    throw "Hidden GyanVerse launcher not found: $launcher"
}

$python = Get-Command python -ErrorAction Stop
$pythonDir = Split-Path -Parent $python.Source
$pythonw = Join-Path $pythonDir "pythonw.exe"
if (-not (Test-Path -LiteralPath $pythonw -PathType Leaf)) {
    throw "pythonw.exe not found next to: $($python.Source)"
}

$process = Start-Process -FilePath $pythonw `
    -ArgumentList @('"' + $launcher + '"') `
    -WorkingDirectory $root `
    -WindowStyle Hidden `
    -PassThru

Write-Host "GyanVerse Academy started without a console window. PID: $($process.Id)"
Write-Host "Log: $(Join-Path $root 'data\logs')"
