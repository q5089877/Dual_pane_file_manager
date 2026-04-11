@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0.."

echo --------------------------------------------------------
echo   DualPaneFileManager - Portable Build
echo --------------------------------------------------------

:: Set Python (prefer venv)
set "PYTHON_EXE=python"
if exist "venv\Scripts\python.exe" (
    set "PYTHON_EXE=venv\Scripts\python.exe"
    echo [INFO] Using virtual environment: venv
)

:: Check PyInstaller
"%PYTHON_EXE%" -m PyInstaller --version >nul 2>&1
if %errorlevel% neq 0 (
    echo [INFO] Installing PyInstaller...
    "%PYTHON_EXE%" -m pip install pyinstaller
)

:: Build
echo [INFO] Running PyInstaller...
"%PYTHON_EXE%" -m PyInstaller --clean --noconfirm DualPaneFileManager.spec

if %errorlevel% neq 0 (
    echo [ERROR] Build failed. Check logs above.
    pause
    exit /b 1
)

:: Copy config.example.json as default config.json into dist
set "DIST_DIR=%cd%\dist\DualPaneFileManager"
if not exist "%DIST_DIR%\config.json" (
    if exist "config.example.json" (
        copy /Y "config.example.json" "%DIST_DIR%\config.json" >nul
        echo [INFO] Copied config.example.json -> dist\DualPaneFileManager\config.json
    )
)

:: Create release zip
set "ZIP_NAME=DualPaneFileManager-portable.zip"
if exist "%ZIP_NAME%" del "%ZIP_NAME%"
powershell -Command "Compress-Archive -Path '%DIST_DIR%' -DestinationPath '%ZIP_NAME%'" >nul 2>&1
if %errorlevel% equ 0 (
    echo [INFO] Release zip created: %ZIP_NAME%
)

echo --------------------------------------------------------
echo [SUCCESS] Build complete.
echo   Folder : dist\DualPaneFileManager\
echo   Zip    : %ZIP_NAME%
echo --------------------------------------------------------
pause
