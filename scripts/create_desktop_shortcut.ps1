#Requires -Version 5.1
param(
    [Parameter(Mandatory=$true)]
    [string]$ExePath
)

$ErrorActionPreference = "Stop"

if (-not (Test-Path $ExePath)) {
    throw "ExileLens executable not found: $ExePath"
}

$DesktopPath = [Environment]::GetFolderPath("DesktopDirectory")
$ShortcutPath = Join-Path $DesktopPath "ExileLens.lnk"

$Shell = New-Object -ComObject WScript.Shell
$Shortcut = $Shell.CreateShortcut($ShortcutPath)
$Shortcut.TargetPath = $ExePath
$Shortcut.WorkingDirectory = Split-Path $ExePath
$Shortcut.Description = "ExileLens - Build-aware item analysis for Path of Exile 2"
$Shortcut.Save()

Write-Host "Created desktop shortcut: $ShortcutPath"