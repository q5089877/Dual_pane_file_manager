@echo off
cd /d "%~dp0"
"%~dp0venv\Scripts\python.exe" main.py > "%~dp0run_log.txt" 2>&1
echo Exit code: %ERRORLEVEL% >> "%~dp0run_log.txt"
type "%~dp0run_log.txt"
pause
