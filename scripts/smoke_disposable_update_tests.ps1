#Requires -Version 5.1
<#
.SYNOPSIS
  Focused update/rollback TESTS (pytest). This is NOT a binary end-to-end test.

.DESCRIPTION
  Runs the update-system pytest files against the source tree with the normal development Python (or a Python you name in
  $env:EXILELENS_TEST_PYTHON). It never touches the normal ExileLens install, and it never installs anything into .release-venv:
  the release venv holds only the hash-locked release dependencies (scripts\release_python_preflight.ps1 enforces that).

  Optionally builds ExileLensUpdater.exe once when -BuildUpdater is set (release venv, the same build_updater.ps1 the release uses).

  The real 0.6.0 -> packaged release-candidate update with the real binaries is a separate manual/VM procedure (1.0-E).
#>
param(
    [switch]$BuildUpdater
)

$ErrorActionPreference = "Stop"
$RepoRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
$env:PYTHONPATH = Join-Path $RepoRoot "src"

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
    "tests/test_r2_p0_update_trust.py",
    "tests/test_r2_p0_updater_transaction.py",
    "public_tests/test_support_05_github_release_updates.py"
)
Push-Location $RepoRoot
try {
    if ($env:EXILELENS_TEST_PYTHON) {
        & $env:EXILELENS_TEST_PYTHON -m pytest -q -o addopts= @pytestTargets
    }
    else {
        & py -3.12 -m pytest -q -o addopts= @pytestTargets
    }
    if ($LASTEXITCODE -ne 0) { throw "Disposable update pytest run failed." }
}
finally {
    Pop-Location
}
Write-Host "Disposable update tests passed (pytest only; not a binary end-to-end run)."
