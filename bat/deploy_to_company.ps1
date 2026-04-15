# DualPaneFileManager - Company Deploy Script
# Usage: Right-click → "Run with PowerShell"
# Extracts the portable zip to %USERPROFILE%\DevRepositories\SHL\DualPaneApp

$ErrorActionPreference = "Stop"

$targetDir = Join-Path $env:USERPROFILE "DevRepositories\SHL\DualPaneApp"
$zipName   = "DualPaneFileManager-portable.zip"
$zipPath   = Join-Path $PSScriptRoot "..\$zipName"

# If zip not next to script, look in same folder as script
if (-not (Test-Path $zipPath)) {
    $zipPath = Join-Path $PSScriptRoot $zipName
}

if (-not (Test-Path $zipPath)) {
    Write-Host "[ERROR] Cannot find $zipName" -ForegroundColor Red
    Write-Host "  Looked in: $zipPath"
    Read-Host "Press Enter to exit"
    exit 1
}

Write-Host "Target : $targetDir"
Write-Host "Source : $zipPath"
Write-Host ""

# Create target directory
if (-not (Test-Path $targetDir)) {
    New-Item -ItemType Directory -Path $targetDir -Force | Out-Null
    Write-Host "[OK] Created $targetDir"
}

# Extract (overwrite existing files, but skip config.json if it already exists)
Write-Host "[INFO] Extracting..."
Add-Type -AssemblyName System.IO.Compression.FileSystem
$zip = [System.IO.Compression.ZipFile]::OpenRead($zipPath)

foreach ($entry in $zip.Entries) {
    # Strip the top-level folder name from the zip (DualPaneFileManager/)
    $relativePath = $entry.FullName -replace '^[^/\\]+[/\\]', ''
    if ([string]::IsNullOrEmpty($relativePath)) { continue }

    $destPath = Join-Path $targetDir $relativePath

    if ($entry.FullName.EndsWith('/') -or $entry.FullName.EndsWith('\')) {
        # Directory entry
        if (-not (Test-Path $destPath)) {
            New-Item -ItemType Directory -Path $destPath -Force | Out-Null
        }
    } else {
        # File entry — skip config.json if user already has one (preserve settings)
        $fileName = Split-Path $relativePath -Leaf
        if ($fileName -eq "config.json" -and (Test-Path $destPath)) {
            Write-Host "[SKIP] config.json already exists, keeping your settings"
            continue
        }

        $destDir = Split-Path $destPath -Parent
        if (-not (Test-Path $destDir)) {
            New-Item -ItemType Directory -Path $destDir -Force | Out-Null
        }

        $stream = $entry.Open()
        $fileStream = [System.IO.File]::Create($destPath)
        $stream.CopyTo($fileStream)
        $fileStream.Close()
        $stream.Close()
    }
}

$zip.Dispose()

# Create Desktop shortcut
$exePath = Join-Path $targetDir "DualPaneFileManager.exe"
$shortcutPath = Join-Path ([Environment]::GetFolderPath("Desktop")) "DualPaneFileManager.lnk"

if (Test-Path $exePath) {
    $shell    = New-Object -ComObject WScript.Shell
    $shortcut = $shell.CreateShortcut($shortcutPath)
    $shortcut.TargetPath       = $exePath
    $shortcut.WorkingDirectory = $targetDir
    $shortcut.Description      = "DualPaneFileManager"
    $shortcut.Save()
    Write-Host "[OK] Desktop shortcut created"
}

Write-Host ""
Write-Host "[SUCCESS] Installed to: $targetDir" -ForegroundColor Green
Write-Host "  Run: $exePath"
Write-Host ""
Read-Host "Press Enter to exit"
