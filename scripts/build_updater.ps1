#Requires -Version 5.1
$ErrorActionPreference = "Stop"
$RepoRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
$DistDir = Join-Path $RepoRoot "dist\ExileLens\_internal"
$SpecPath = Join-Path $RepoRoot "packaging\exilelens-updater.spec"
. (Join-Path $PSScriptRoot "release_python_preflight.ps1")
$ReleaseVenv = Assert-ReleaseVenvPreflight -RepoRoot $RepoRoot
$PythonExe = $ReleaseVenv.Executable
$env:PYTHONPATH = Join-Path $RepoRoot "src"
New-Item -ItemType Directory -Force -Path $DistDir | Out-Null
& $PythonExe -m PyInstaller $SpecPath --noconfirm --clean
if ($LASTEXITCODE -ne 0) { throw "Updater build failed" }
$Built = Join-Path $RepoRoot "dist\ExileLensUpdater\ExileLensUpdater.exe"
$Target = Join-Path $DistDir "ExileLensUpdater.exe"
Copy-Item -LiteralPath $Built -Destination $Target -Force
Write-Host "Updater copied to $Target"
