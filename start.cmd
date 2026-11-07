@echo off
cd /d "%~dp0"
where pyw >nul 2>nul
if not errorlevel 1 (start "" pyw -3 scripts\desktop.py & exit /b)
where pythonw >nul 2>nul
if not errorlevel 1 (start "" pythonw scripts\desktop.py & exit /b)
echo Install Python 3.10+ from https://www.python.org/downloads/ first.
echo Then double-click start.cmd again.
pause
