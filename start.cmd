@echo off
cd /d "%~dp0"
where py >nul 2>nul
if errorlevel 1 (python scripts\start.py) else (py -3 scripts\start.py)
if errorlevel 1 (echo Collection needs attention. Please read the message above.) else (echo Done. Documents are in the configured output folder.)
pause
