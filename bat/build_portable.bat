@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0.."
echo --------------------------------------------------------
echo   Starting Portable Bundle Build...
echo --------------------------------------------------------

:: Set Python to use (prefer venv)
set "PYTHON_EXE=python"
if exist "venv\Scripts\python.exe" (
    set "PYTHON_EXE=venv\Scripts\python.exe"
    echo [INFO] Using virtual environment: venv
)

:: Check if PyInstaller is installed in the selected environment
"%PYTHON_EXE%" -m PyInstaller --version >nul 2>&1
if %errorlevel% neq 0 (
    echo [INFO] Installing PyInstaller in the current environment...
    "%PYTHON_EXE%" -m pip install pyinstaller
)

:: Run build using .spec file
echo [INFO] Running PyInstaller with DoubleFileExplorer.spec...
"%PYTHON_EXE%" -m PyInstaller --clean --noconfirm DoubleFileExplorer.spec

if %errorlevel% equ 0 (
    echo --------------------------------------------------------
    echo [SUCCESS] Portable Bundle created at: %cd%\dist\DoubleFileExplorer
    echo You can now copy this folder to K: for your colleagues.
    echo --------------------------------------------------------
) else (
    echo [ERROR] Build failed. Please check the logs above.
)

pause
