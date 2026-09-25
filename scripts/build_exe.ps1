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
