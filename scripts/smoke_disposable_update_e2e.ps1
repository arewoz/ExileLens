#Requires -Version 5.1
<#
.SYNOPSIS
  Controlled disposable update/rollback smoke (never touches the normal ExileLens install).

.DESCRIPTION
  Runs focused pytest coverage for install, rollback, settings preservation, and manifest signing.
  Optionally builds ExileLensUpdater.exe once when -BuildUpdater is set.
#>
param(
    [switch]$BuildUpdater
)

$ErrorActionPreference = "Stop"
$RepoRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
$env:PYTHONPATH = Join-Path $RepoRoot "src"
$env:EXILELENS_DISPOSABLE_E2E = "1"

if ($BuildUpdater) {
    Write-Host "Building ExileLensUpdater.exe (release venv)..."
    & (Join-Path $RepoRoot "scripts\build_updater.ps1")
    if ($LASTEXITCODE -ne 0) { throw "Updater build failed." }
    $built = Join-Path $RepoRoot "dist\ExileLensUpdater.exe"
    if (-not (Test-Path -LiteralPath $built)) {
        throw "Expected updater binary missing: $built"
    }
    Write-Host "Updater packaging smoke OK: $built"
}

$pytestTargets = @(
    "tests/test_m4_2_update_system.py",
    "public_tests/test_support_05_github_release_updates.py"
)
$releasePy = Join-Path $RepoRoot ".release-venv\Scripts\python.exe"
$testPy = if (Test-Path -LiteralPath $releasePy) { $releasePy } else { "py" }
Push-Location $RepoRoot
try {
    if ($testPy -eq "py") {
        & py -3.12 -m pytest -q -o addopts= @pytestTargets
    }
    else {
        & $testPy -m pip install --disable-pip-version-check pytest -q 2>$null | Out-Null
        & $testPy -m pytest -q -o addopts= @pytestTargets
    }
}
finally {
    Pop-Location
}
if ($LASTEXITCODE -ne 0) { throw "Disposable update E2E pytest failed." }
Write-Host "Disposable update E2E smoke passed."
