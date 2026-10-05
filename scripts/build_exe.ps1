#Requires -Version 5.1
param(
    [switch]$SkipShortcut
)

$ErrorActionPreference = "Stop"

$RepoRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
$DistDir = Join-Path $RepoRoot "dist\ExileLens"
$ExePath = Join-Path $DistDir "ExileLens.exe"
$SpecPath = Join-Path $RepoRoot "packaging\exilelens-gui.spec"
$BuildDir = Join-Path $RepoRoot "build\exilelens-gui"
$CollectToc = Join-Path $BuildDir "COLLECT-00.toc"
$BinaryManifestPath = Join-Path $DistDir "binary_manifest.json"
$ProvenanceScript = Join-Path $PSScriptRoot "validate_release_binary_provenance.py"
$Commit = (git -C $RepoRoot rev-parse HEAD).Trim()
if ($Commit -notmatch '^[0-9a-f]{40}$') { throw "Could not establish a full source commit for this build" }

. (Join-Path $PSScriptRoot "release_python_preflight.ps1")
$ReleaseVenv = Assert-ReleaseVenvPreflight -RepoRoot $RepoRoot
$PythonExe = $ReleaseVenv.Executable

function Get-CanonicalVersion {
    $env:PYTHONPATH = Join-Path $RepoRoot "src"
    $value = (& $PythonExe -c "from exilelens._version import __version__; print(__version__)").Trim()
    if (-not $value) { throw "Failed to read canonical version from exilelens._version" }
    return $value
}

Push-Location $RepoRoot
$OriginalPath = $env:PATH
$OriginalPythonPath = $env:PYTHONPATH
try {
    # This affects only child processes of this build. It deliberately excludes
    # arbitrary developer, Codex, Poppler, and other host PATH entries.
    $env:PATH = Get-ControlledReleaseBuildPath -ReleaseVenvRoot $ReleaseVenv.Root
    $env:PYTHONPATH = Join-Path $RepoRoot "src"

    Write-Host "==> Regenerating Windows version resources..."
    & $PythonExe (Join-Path $PSScriptRoot "generate_packaging_version_info.py")
    if ($LASTEXITCODE -ne 0) { throw "version resource generation failed" }

    Write-Host "==> Regenerating application icon..."
    & $PythonExe (Join-Path $PSScriptRoot "make_app_icon.py")
    if ($LASTEXITCODE -ne 0) { throw "icon generation failed" }

    Write-Host "==> Building Windows GUI executable..."
    & $PythonExe -m PyInstaller $SpecPath --noconfirm --clean
    if ($LASTEXITCODE -ne 0) { throw "PyInstaller build failed" }

    if (-not (Test-Path $ExePath)) {
        throw "Expected executable not found: $ExePath"
    }

    # Ship the install/setup/troubleshooting guide alongside the executable;
    # release.yml zips this directory verbatim.
    Copy-Item -LiteralPath (Join-Path $RepoRoot "packaging\README.txt") -Destination (Join-Path $DistDir "README.txt") -Force
    # Distribution compliance (1.0-A): the project license, the third-party notices and the verified third-party license texts ship
    # next to the executable. The release gate (release_gate._distribution_files) fails the release if any of them is missing.
    Copy-Item -LiteralPath (Join-Path $RepoRoot "LICENSE") -Destination (Join-Path $DistDir "LICENSE") -Force
    Copy-Item -LiteralPath (Join-Path $RepoRoot "packaging\THIRD_PARTY_NOTICES.txt") -Destination (Join-Path $DistDir "THIRD_PARTY_NOTICES.txt") -Force
    Copy-Item -LiteralPath (Join-Path $RepoRoot "packaging\QT_LGPL_COMPLIANCE.txt") -Destination (Join-Path $DistDir "QT_LGPL_COMPLIANCE.txt") -Force
    $ThirdPartyLicenseDest = Join-Path $DistDir "third_party_licenses"
    if (Test-Path -LiteralPath $ThirdPartyLicenseDest) { Remove-Item -LiteralPath $ThirdPartyLicenseDest -Recurse -Force }
    Copy-Item -LiteralPath (Join-Path $RepoRoot "packaging\third_party_licenses") -Destination $ThirdPartyLicenseDest -Recurse -Force

    # The updater is built EXACTLY ONCE, here, before provenance is recorded: the binary that is hashed, validated and gated
    # is the binary that ships (release.yml no longer builds it again). It is staged into _internal by build_updater.ps1.
    Write-Host "==> Building and staging external updater (once)..."
    & (Join-Path $PSScriptRoot "build_updater.ps1")
    if ($LASTEXITCODE -ne 0) { throw "Updater build failed" }
    $UpdaterPath = Join-Path $DistDir "_internal\ExileLensUpdater.exe"
    if (-not (Test-Path -LiteralPath $UpdaterPath)) {
        throw "Expected updater not staged in distribution: $UpdaterPath"
    }
    $UpdaterBuilt = Join-Path $RepoRoot "dist\ExileLensUpdater.exe"

    $Version = Get-CanonicalVersion
    if ($Version -notmatch '^\d+\.\d+\.\d+(b\d+)?$') { throw "Canonical version has an unsupported format: $Version" }
    $Deps = Get-BuildDependencyVersions -PythonExecutable $PythonExe
    if (-not (Test-Path $CollectToc)) { throw "Missing PyInstaller collection metadata: $CollectToc" }
    Write-Host "==> Validating collected native-binary provenance..."
    & $PythonExe $ProvenanceScript `
        --repo-root $RepoRoot `
        --venv-root $ReleaseVenv.Root `
        --build-root $BuildDir `
        --dist-root $DistDir `
        --collect-toc $CollectToc `
        --updater-built $UpdaterBuilt `
        --manifest $BinaryManifestPath `
        --git-commit $Commit `
        --application-version $Version `
        --system-root (Join-Path $env:SystemRoot "System32") `
        --system-root $env:SystemRoot `
        --approved-root $ReleaseVenv.BaseRuntimeRoot
    if ($LASTEXITCODE -ne 0) { throw "Collected native-binary provenance validation failed" }
    $StampPath = Join-Path $DistDir "build_stamp.json"
    $Stamp = @{
        schema_version      = 1
        product             = "ExileLens"
        version             = $Version
        git_commit          = $Commit
        unsigned            = $true
        build_mode          = "onedir"
        python_version      = $Deps.python_version
        pyinstaller_version = $Deps.pyinstaller_version
        pyside6_version     = $Deps.pyside6_version
        binary_manifest     = "binary_manifest.json"
        updater             = "_internal/ExileLensUpdater.exe"
    } | ConvertTo-Json -Compress
    [System.IO.File]::WriteAllText($StampPath, $Stamp)

    Write-Host ("==> Build metadata: python={0} pyinstaller={1} git={2} mode=onedir" -f $Deps.python_version, $Deps.pyinstaller_version, $Commit)
    Write-Host "==> Build complete: $ExePath ($Version)"
    if (-not $SkipShortcut) {
        & (Join-Path $PSScriptRoot "create_desktop_shortcut.ps1") -ExePath $ExePath
    }
}
finally {
    $env:PATH = $OriginalPath
    $env:PYTHONPATH = $OriginalPythonPath
    Pop-Location
}
