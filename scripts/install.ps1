param([string]$PythonExecutable = '')
$ErrorActionPreference = 'Stop'
Set-Location (Split-Path $PSScriptRoot -Parent)
if (-not (Test-Path -LiteralPath 'config.json')) {
    Copy-Item -LiteralPath 'config.example.json' -Destination 'config.json'
}
if (-not (Test-Path '.venv\Scripts\python.exe')) {
    if ($PythonExecutable) {
        & $PythonExecutable -m venv .venv
    } else {
        py -3 -m venv .venv
    }
    if ($LASTEXITCODE -ne 0) { throw 'Install Python 3.10+ from python.org, then retry.' }
}
& .\.venv\Scripts\python.exe -m pip install -e .
if ($LASTEXITCODE -ne 0) { throw 'Installation failed.' }
& .\.venv\Scripts\collect.exe doctor
