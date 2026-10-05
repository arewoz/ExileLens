#Requires -Version 5.1
<#
.SYNOPSIS
  Proves on a BUILT package that the Qt libraries are separate, replaceable files that ExileLens really loads from the package folder
  (the LGPL-3.0 "replace the library" route in QT_LGPL_COMPLIANCE.txt). Nothing in the original package is touched.

.DESCRIPTION
  Works on a temporary COPY of dist\ExileLens with an isolated LOCALAPPDATA (never your real ExileLens profile) and POB2_PATH unset:
    1. baseline   : start ExileLens.exe, list the Qt DLLs the process actually loaded and where from, quit cleanly;
    2. modified   : replace _internal\PySide6\Qt6Core.dll with a different, still valid copy (original bytes + a 16-byte overlay, so a
                    different SHA-256), start again and show that the loaded Qt6Core.dll is the replacement;
    3. incompatible: replace it with garbage; the application must NOT start (proves the file really is what gets loaded);
    4. restore    : put the original back, start once more, and show every file of the copy is byte-identical to the original package.
  Refuses to run if an ExileLens process is already running (the single-instance mutex would hand the launch to it).
#>
param(
    [string]$PackageDir = (Join-Path (Resolve-Path (Join-Path $PSScriptRoot "..")) "dist\ExileLens"),
    [int]$StartTimeoutSeconds = 60,
    [switch]$KeepWorkDir
)

$ErrorActionPreference = "Stop"
if (Get-Process -Name ExileLens -ErrorAction SilentlyContinue) { throw "An ExileLens process is already running; close it first." }
$PackageDir = (Resolve-Path $PackageDir).Path
$Work = Join-Path ([System.IO.Path]::GetTempPath()) ("el-qt-replace-" + [guid]::NewGuid().ToString("N").Substring(0, 8))
$Copy = Join-Path $Work "ExileLens"
$Profile = Join-Path $Work "local"
New-Item -ItemType Directory -Force -Path $Profile | Out-Null
Copy-Item -LiteralPath $PackageDir -Destination $Copy -Recurse -Force
$Core = Join-Path $Copy "_internal\PySide6\Qt6Core.dll"
$CoreBackup = Join-Path $Work "Qt6Core.dll.original"
Copy-Item -LiteralPath $Core -Destination $CoreBackup -Force

$savedLocal = $env:LOCALAPPDATA; $savedAppData = $env:APPDATA; $savedPob = $env:POB2_PATH
$env:LOCALAPPDATA = $Profile; $env:APPDATA = $Profile; Remove-Item Env:POB2_PATH -ErrorAction SilentlyContinue
$results = [ordered]@{}

function Start-Probe([string]$Label) {
    $log = Join-Path $Profile "ExileLens\logs\poe2value.log"
    if (Test-Path $log) { Remove-Item -LiteralPath $log -Force }
    $proc = Start-Process -FilePath (Join-Path $Copy "ExileLens.exe") -PassThru -WorkingDirectory $Copy
    $deadline = (Get-Date).AddSeconds($StartTimeoutSeconds)
    $ready = $false
    while ((Get-Date) -lt $deadline -and -not $proc.HasExited) {
        Start-Sleep -Milliseconds 500
        if ((Test-Path $log) -and (Select-String -LiteralPath $log -Pattern "tray_ready" -Quiet)) { $ready = $true; break }
    }
    $modules = @()
    if ($ready) {
        $proc.Refresh()
        $modules = @($proc.Modules | Where-Object { $_.FileName -like "$Copy*" -and $_.ModuleName -match '^(Qt6|qwindows|qjpeg|qsvg|qgif|qico|qmodernwindowsstyle|qschannel|qcertonly|qopenssl|qdirect2d|qminimal|qoffscreen|qnetworklist|qtuiotouch)' } |
            ForEach-Object { [pscustomobject]@{ Name = $_.ModuleName; Path = $_.FileName.Substring($Copy.Length + 1); Sha256 = (Get-FileHash -LiteralPath $_.FileName -Algorithm SHA256).Hash.ToLowerInvariant() } })
    }
    if ($ready) {
        Start-Process -FilePath (Join-Path $Copy "ExileLens.exe") -ArgumentList "--quit" -Wait -WindowStyle Hidden | Out-Null
        if (-not $proc.WaitForExit(30000)) { $proc.Kill() }
    }
    elseif (-not $proc.HasExited) { $proc.Kill(); $proc.WaitForExit(10000) | Out-Null }
    return [pscustomobject]@{ Label = $Label; Started = $ready; Modules = $modules }
}

try {
    $baseline = Start-Probe "baseline"
    if (-not $baseline.Started) { throw "baseline did not reach tray_ready" }
    $originalHash = (Get-FileHash -LiteralPath $CoreBackup -Algorithm SHA256).Hash.ToLowerInvariant()
    $results["baseline_qt_modules_loaded"] = $baseline.Modules
    $results["baseline_loads_from_package_folder"] = (@($baseline.Modules | Where-Object { $_.Name -eq "Qt6Core.dll" -and $_.Path -eq "_internal\PySide6\Qt6Core.dll" }).Count -eq 1)

    # 2. modified, still valid
    [System.IO.File]::WriteAllBytes($Core, ([System.IO.File]::ReadAllBytes($CoreBackup) + [byte[]](1..16)))
    $modifiedHash = (Get-FileHash -LiteralPath $Core -Algorithm SHA256).Hash.ToLowerInvariant()
    $modified = Start-Probe "modified"
    $loadedCore = $modified.Modules | Where-Object { $_.Name -eq "Qt6Core.dll" }
    $results["modified_started"] = $modified.Started
    $results["modified_loaded_hash_is_the_replacement"] = ($null -ne $loadedCore -and $loadedCore.Sha256 -eq $modifiedHash -and $modifiedHash -ne $originalHash)

    # 3. incompatible
    [System.IO.File]::WriteAllBytes($Core, [byte[]](0..255))
    $broken = Start-Probe "incompatible"
    $results["incompatible_replacement_prevents_start"] = (-not $broken.Started)

    # 4. restore
    Copy-Item -LiteralPath $CoreBackup -Destination $Core -Force
    $restored = Start-Probe "restored"
    $results["restored_started"] = $restored.Started
    $diff = @()
    foreach ($file in Get-ChildItem -LiteralPath $PackageDir -Recurse -File) {
        $rel = $file.FullName.Substring($PackageDir.Length + 1)
        $other = Join-Path $Copy $rel
        if (-not (Test-Path -LiteralPath $other) -or (Get-FileHash -LiteralPath $file.FullName -Algorithm SHA256).Hash -ne (Get-FileHash -LiteralPath $other -Algorithm SHA256).Hash) { $diff += $rel }
    }
    # files the application itself wrote into its own folder while running (none expected)
    $extra = @(Get-ChildItem -LiteralPath $Copy -Recurse -File | Where-Object { -not (Test-Path -LiteralPath (Join-Path $PackageDir $_.FullName.Substring($Copy.Length + 1))) } | ForEach-Object { $_.FullName.Substring($Copy.Length + 1) })
    $results["restored_files_differing_from_package"] = $diff
    $results["files_added_by_running_the_copy"] = $extra
}
finally {
    $env:LOCALAPPDATA = $savedLocal; $env:APPDATA = $savedAppData
    if ($null -ne $savedPob) { $env:POB2_PATH = $savedPob }
    Get-Process -Name ExileLens -ErrorAction SilentlyContinue | Where-Object { $_.Path -like "$Copy*" } | Stop-Process -Force -ErrorAction SilentlyContinue
    if (-not $KeepWorkDir) { Remove-Item -LiteralPath $Work -Recurse -Force -ErrorAction SilentlyContinue }
}
$results | ConvertTo-Json -Depth 5
$ok = $results["baseline_loads_from_package_folder"] -and $results["modified_started"] -and $results["modified_loaded_hash_is_the_replacement"] -and
      $results["incompatible_replacement_prevents_start"] -and $results["restored_started"] -and ($results["restored_files_differing_from_package"].Count -eq 0)
if (-not $ok) { Write-Error "Qt replacement proof FAILED"; exit 1 }
Write-Host "Qt replacement proof PASSED (the original package was not modified)."
