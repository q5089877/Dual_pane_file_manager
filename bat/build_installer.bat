@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0.."

echo --------------------------------------------------------
echo   DualPaneFileManager - Installer Build
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

:: ── Step 1: 清除舊的 dist 避免殘留舊程式 ───────────────────
if exist "dist\DualPaneFileManager" (
    echo [INFO] Removing old dist\DualPaneFileManager...
    rmdir /s /q "dist\DualPaneFileManager"
)

:: ── Step 2: PyInstaller ──────────────────────────────────
echo [INFO] Running PyInstaller...
"%PYTHON_EXE%" -m PyInstaller --clean --noconfirm DualPaneFileManager.spec
if %errorlevel% neq 0 (
    echo [ERROR] PyInstaller build failed.
    pause & exit /b 1
)

:: ── Step 2: 複製預設 config ───────────────────────────────
set "DIST_DIR=%cd%\dist\DualPaneFileManager"
if not exist "%DIST_DIR%\config.json" (
    if exist "config.example.json" (
        copy /Y "config.example.json" "%DIST_DIR%\config.json" >nul
        echo [INFO] Copied config.example.json -> dist\DualPaneFileManager\config.json
    )
)

:: ── Step 3: 萃取版本號並同步至 installer.iss ─────────────
for /f "tokens=2 delims==" %%I in ('findstr "APP_VERSION" "core\config_manager.py"') do set RAW_VERSION=%%I
set "APP_VERSION=%RAW_VERSION:"=%"
set "APP_VERSION=%APP_VERSION: =%"
echo [INFO] Detected version: %APP_VERSION%

powershell -Command "(Get-Content 'installer.iss') -replace '^AppVersion=.*', 'AppVersion=%APP_VERSION%' | Set-Content 'installer.iss'"
echo [INFO] Synced AppVersion=%APP_VERSION% -> installer.iss

:: ── Step 4: 找 Inno Setup Compiler ───────────────────────
set "ISCC="
if exist "C:\Program Files (x86)\Inno Setup 6\ISCC.exe" set "ISCC=C:\Program Files (x86)\Inno Setup 6\ISCC.exe"
if exist "C:\Program Files\Inno Setup 6\ISCC.exe"       set "ISCC=C:\Program Files\Inno Setup 6\ISCC.exe"
if exist "C:\Program Files (x86)\Inno Setup 5\ISCC.exe" set "ISCC=C:\Program Files (x86)\Inno Setup 5\ISCC.exe"

if not defined ISCC (
    echo [ERROR] Inno Setup Compiler (ISCC.exe) not found.
    echo         Install from: https://jrsoftware.org/isdl.php
    pause & exit /b 1
)

:: ── Step 5: 編譯 installer ───────────────────────────────
echo [INFO] Compiling installer...
"%ISCC%" installer.iss
if %errorlevel% neq 0 (
    echo [ERROR] Inno Setup compilation failed.
    pause & exit /b 1
)

:: ── Step 6: 產出 portable zip（進目錄打包，避免多一層）────
set "ZIP_NAME=DualPaneFileManager-portable.zip"
if exist "%ZIP_NAME%" del "%ZIP_NAME%"
pushd "%DIST_DIR%"
powershell -Command "Compress-Archive -Path * -DestinationPath '..\..\%ZIP_NAME%'"
popd
if exist "%ZIP_NAME%" (
    echo [INFO] Portable zip created: %ZIP_NAME%
) else (
    echo [WARN] Portable zip was not created.
)

echo --------------------------------------------------------
echo [SUCCESS] Build complete.
echo   Installer : Output\DualPaneFileManager_SHL_Setup.exe
echo   Portable  : %ZIP_NAME%
echo --------------------------------------------------------
pause
