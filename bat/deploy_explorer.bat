@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0.."

:: ============================================================================
:: DualPaneFileManager - Local Install Helper
:: Copies the portable build to a chosen directory and creates a Desktop shortcut
:: ============================================================================

set "SRC_DIR=%cd%\dist\DualPaneFileManager"
set "DEST_DIR=%LOCALAPPDATA%\DualPaneFileManager"

echo --------------------------------------------------------
echo   DualPaneFileManager - Install to Local AppData
echo --------------------------------------------------------
echo Source : %SRC_DIR%
echo Target : %DEST_DIR%
echo --------------------------------------------------------

:: Check source
if not exist "%SRC_DIR%\DualPaneFileManager.exe" (
    echo [ERROR] DualPaneFileManager.exe not found in %SRC_DIR%
    echo Run build_portable.bat first.
    pause
    exit /b 1
)

:: Sync files
echo [INFO] Copying files...
robocopy "%SRC_DIR%" "%DEST_DIR%" /E /XO /R:3 /W:5 /NP

if %ERRORLEVEL% GEQ 8 (
    echo [ERROR] File copy failed. Error: %ERRORLEVEL%
    pause
    exit /b 1
)

echo [SUCCESS] Files copied to %DEST_DIR%

:: Create Desktop shortcut
echo [INFO] Creating Desktop shortcut...
powershell -NoProfile -ExecutionPolicy Bypass -Command ^
    "$ws = New-Object -ComObject WScript.Shell; " ^
    "$desktop = [System.Environment]::GetFolderPath('Desktop'); " ^
    "$shortcut = $ws.CreateShortcut(\"$desktop\DualPaneFileManager.lnk\"); " ^
    "$shortcut.TargetPath = '%DEST_DIR%\DualPaneFileManager.exe'; " ^
    "$shortcut.WorkingDirectory = '%DEST_DIR%'; " ^
    "$shortcut.Save();"

if %ERRORLEVEL% EQU 0 (
    echo [SUCCESS] Shortcut created on Desktop.
) else (
    echo [WARNING] Failed to create shortcut.
)

echo.
set /p "choice=Launch now? (Y/N): "
if /i "%choice%"=="Y" (
    start "" "%DEST_DIR%\DualPaneFileManager.exe"
)

echo.
echo Done.
pause
