$ErrorActionPreference = 'Stop'
Set-Location (Split-Path $PSScriptRoot -Parent)
$python = Join-Path (Get-Location) '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $python)) { throw 'Run scripts/install.ps1 first.' }
$env:PYTHONIOENCODING = 'utf-8'
& $python .\scripts\wps-login.py
exit $LASTEXITCODE