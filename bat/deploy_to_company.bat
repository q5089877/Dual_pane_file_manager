@echo off
chcp 65001 >nul
title DualPaneFileManager - Company Deploy Script
echo 正在啟動安裝程序...

:: 自動以 Bypass 權限呼叫 PowerShell，並透過 -ArgumentList 將當前 BAT 所在目錄 (%~dp0) 傳入記憶體腳本中
powershell -NoProfile -ExecutionPolicy Bypass -Command "& { $content = Get-Content -LiteralPath '%~f0' -Raw -Encoding UTF8; $psCode = $content -replace '(?s)^.*#---START_PS---[\r\n]+', ''; Invoke-Command -ScriptBlock ([scriptblock]::Create($psCode)) -ArgumentList '%~dp0' }"

:: 批次檔執行到此結束，避免執行到下方的 PS 語法
exit /b

#---START_PS---
param([string]$ScriptDir)
$ErrorActionPreference = "Stop"

$targetDir = Join-Path $env:USERPROFILE "DevRepositories\SHL\DualPaneApp"
$zipName   = "DualPaneFileManager-portable.zip"

# $PSScriptRoot 在記憶體執行時為空，改用 BAT 傳入的 $ScriptDir
$zipPath = Join-Path $ScriptDir $zipName
if (-not (Test-Path $zipPath)) {
    $zipPath = Join-Path (Split-Path $ScriptDir -Parent) $zipName
}

if (-not (Test-Path $zipPath)) {
    Write-Host "[ERROR] Cannot find $zipName" -ForegroundColor Red
    Write-Host "  Looked in: $ScriptDir"
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

# Extract — zip 內容直接是檔案（無外層資料夾），直接解壓到 targetDir
Write-Host "[INFO] Extracting..."
Add-Type -AssemblyName System.IO.Compression.FileSystem
$zip = [System.IO.Compression.ZipFile]::OpenRead($zipPath)

foreach ($entry in $zip.Entries) {
    $relativePath = $entry.FullName.Replace('/', '\')
    if ([string]::IsNullOrEmpty($relativePath)) { continue }

    $destPath = Join-Path $targetDir $relativePath

    if ($relativePath.EndsWith('\')) {
        # Directory entry
        if (-not (Test-Path $destPath)) {
            New-Item -ItemType Directory -Path $destPath -Force | Out-Null
        }
    } else {
        # File entry — preserve existing config.json to keep user settings
        $fileName = Split-Path $relativePath -Leaf
        if ($fileName -eq "config.json" -and (Test-Path $destPath)) {
            Write-Host "[SKIP] config.json already exists, keeping your settings" -ForegroundColor Yellow
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
