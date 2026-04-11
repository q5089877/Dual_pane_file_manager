@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0.."

:: ============================================================================
:: SHL DoubleFileExplorer Deployment Tool (Robust Version)
:: ============================================================================

:: Set source and destination paths
set "SRC_DIR=%cd%\DoubleFileExplorer"
set "DEST_ROOT=%USERPROFILE%\DevRepositories\SHL"
set "DEST_DIR=%DEST_ROOT%\DoubleFileExplorer"

echo --------------------------------------------------------
echo   Executing Deployment (Green Folder Mode)...
echo --------------------------------------------------------
echo Source: %SRC_DIR%
echo Destination: %DEST_DIR%
echo --------------------------------------------------------

:: 1. Check Source
if not exist "%SRC_DIR%\DoubleFileExplorer.exe" (
    echo [ERROR] Cannot find DoubleFileExplorer.exe in %SRC_DIR%
    echo Make sure this BAT is placed next to the "DoubleFileExplorer" folder.
    pause
    exit /b 1
)

:: 2. Create Destination Folder
if not exist "%DEST_ROOT%" (
    echo [INFO] Creating safe directory at %DEST_ROOT%...
    mkdir "%DEST_ROOT%" 2>nul
)

:: 3. Run Sync (Robocopy)
echo [INFO] Synchronizing files, please wait...
robocopy "%SRC_DIR%" "%DEST_DIR%" /E /XO /R:3 /W:5 /NP

:: Check result
if %ERRORLEVEL% GEQ 8 (
    echo.
    echo [FAILED] File synchronization failed. Error: %ERRORLEVEL%
    pause
    exit /b 1
)

echo.
echo [SUCCESS] Software deployed to: %DEST_DIR%

:: 4. Create Desktop Shortcut (Using PowerShell for maximum compatibility with OneDrive/Redirection)
echo [INFO] Creating Desktop Shortcut...
powershell -NoProfile -ExecutionPolicy Bypass -Command ^
    "$ws = New-Object -ComObject WScript.Shell; " ^
    "$desktop = [System.Environment]::GetFolderPath('Desktop'); " ^
    "$shortcut = $ws.CreateShortcut(\"$desktop\DoubleFileExplorer.lnk\"); " ^
    "$shortcut.TargetPath = '%DEST_DIR%\DoubleFileExplorer.exe'; " ^
    "$shortcut.WorkingDirectory = '%DEST_DIR%'; " ^
    "$shortcut.Save();"

if %ERRORLEVEL% EQU 0 (
    echo [SUCCESS] Shortcut created on Desktop.
) else (
    echo [WARNING] Failed to create shortcut automatically.
)

echo.
set /p "choice=Do you want to start the application now? (Y/N): "
if /i "%choice%"=="Y" (
    start "" "%DEST_DIR%\DoubleFileExplorer.exe"
)

echo.
echo Deployment finished.
pause
