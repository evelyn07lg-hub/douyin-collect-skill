$ErrorActionPreference = 'Stop'
Set-Location (Split-Path $PSScriptRoot -Parent)
$python = Join-Path (Get-Location) '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $python)) { throw 'Run scripts/install.ps1 first.' }
& $python -m pip install 'playwright>=1.48,<2'
if ($LASTEXITCODE -ne 0) { throw 'Playwright installation failed. Please keep the error output.' }
$env:PYTHONIOENCODING = 'utf-8'
& $python .\scripts\browser-probe.py
exit $LASTEXITCODE
