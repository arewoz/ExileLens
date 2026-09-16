#Requires -Version 5.1
# Shared release-build Python version gate. Reads .python-version (single source of truth).

function Get-ReleasePythonPinnedVersion {
    param([string]$RepoRoot)
    $path = Join-Path $RepoRoot ".python-version"
    if (-not (Test-Path $path)) {
        throw "Missing release Python pin: $path"
    }
    $value = (Get-Content -Path $path -Raw).Trim()
    if ($value -notmatch '^\d+\.\d+\.\d+$') {
        throw ".python-version must contain major.minor.patch, got: $value"
    }
    return $value
}

function Get-PythonVersionTuple {
    param([string]$Executable, [string[]]$PrefixArgs = @())
    $output = & $Executable @($PrefixArgs + @(
        "-c",
        "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}')"
    ))
    if ($LASTEXITCODE -ne 0 -or -not $output) {
        throw "Failed to read Python version from $Executable"
    }
    $parts = $output.Trim().Split('.')
    return @{
        Major = [int]$parts[0]
        Minor = [int]$parts[1]
        Patch = [int]$parts[2]
        Text  = $output.Trim()
    }
}

function Resolve-ReleasePython {
    param([string]$RepoRoot)
    $pinned = Get-ReleasePythonPinnedVersion -RepoRoot $RepoRoot
    $parts = $pinned.Split('.')
    $major = $parts[0]
    $minor = $parts[1]

    $candidates = @(
        @{ Label = "py -$major.$minor"; Executable = "py"; PrefixArgs = @("-$major.$minor") },
        @{ Label = "python on PATH"; Executable = "python"; PrefixArgs = @() }
    )

    foreach ($candidate in $candidates) {
        try {
            $version = Get-PythonVersionTuple -Executable $candidate.Executable -PrefixArgs $candidate.PrefixArgs
            if ($version.Text -eq $pinned) {
                $resolvedExe = & $candidate.Executable @($candidate.PrefixArgs + @(
                    "-c", "import sys; print(sys.executable)"
                ))
                if ($LASTEXITCODE -ne 0 -or -not $resolvedExe) {
                    continue
                }
                return @{
                    PinnedVersion = $pinned
                    Executable    = $resolvedExe.Trim()
                    VersionText   = $version.Text
                    Source        = $candidate.Label
                }
            }
        }
        catch {
            continue
        }
    }

    $active = ""
    try {
        $activeVersion = Get-PythonVersionTuple -Executable "python"
        $active = $activeVersion.Text
    }
    catch {
        $active = "(python not found)"
    }

    throw @(
        "Release build requires Python $pinned (see .python-version)."
        "Active interpreter: Python $active."
        "Install Python $pinned and run with: py -$major.$minor scripts\build_exe.ps1"
        "Source compatibility remains requires-python >=3.10; this pin applies to release builds only."
    ) -join "`n"
}

function Assert-ReleasePythonPreflight {
    param([string]$RepoRoot)
    $resolved = Resolve-ReleasePython -RepoRoot $RepoRoot
    Write-Host ("==> Release Python preflight: {0} ({1})" -f $resolved.VersionText, $resolved.Source)
    return $resolved
}

function Get-ReleaseDependencyPins {
    param([string]$RepoRoot)
    $requirements = Join-Path $RepoRoot "packaging\requirements-release.txt"
    if (-not (Test-Path $requirements)) {
        throw "Missing pinned release requirements: $requirements"
    }
    $pins = @{}
    foreach ($line in Get-Content -Path $requirements) {
        $text = $line.Trim()
        if (-not $text -or $text.StartsWith("#")) { continue }
        if ($text -notmatch '^([A-Za-z0-9_.-]+)==([A-Za-z0-9_.+!-]+)$') {
            throw "Release requirements must use exact package pins, got: $text"
        }
        $pins[$Matches[1]] = $Matches[2]
    }
    if ($pins.Count -eq 0) { throw "Release requirements contain no package pins: $requirements" }
    return $pins
}

function Test-ReleaseVenv {
    param([string]$PythonExecutable, [string]$PinnedVersion, [hashtable]$Pins)
    if (-not (Test-Path $PythonExecutable)) { return $false }
    try {
        $version = Get-PythonVersionTuple -Executable $PythonExecutable
        if ($version.Text -ne $PinnedVersion) { return $false }
        foreach ($name in $Pins.Keys) {
            $installed = (& $PythonExecutable -c "import importlib.metadata as m; print(m.version('$name'))").Trim()
            if ($LASTEXITCODE -ne 0 -or $installed -ne $Pins[$name]) { return $false }
        }
        return $true
    }
    catch {
        return $false
    }
}

function Assert-ReleaseVenvPreflight {
    param([string]$RepoRoot)
    $base = Assert-ReleasePythonPreflight -RepoRoot $RepoRoot
    $venvRoot = Join-Path $RepoRoot ".release-venv"
    $venvPython = Join-Path $venvRoot "Scripts\python.exe"
    $pins = Get-ReleaseDependencyPins -RepoRoot $RepoRoot

    if (-not (Test-Path $venvPython)) {
        Write-Host "==> Creating isolated release venv: $venvRoot"
        & $base.Executable -m venv $venvRoot
        if ($LASTEXITCODE -ne 0) { throw "Could not create release venv: $venvRoot" }
    }
    if (-not (Test-ReleaseVenv -PythonExecutable $venvPython -PinnedVersion $base.PinnedVersion -Pins $pins)) {
        Write-Host "==> Installing pinned release dependencies..."
        & $venvPython -m pip install --disable-pip-version-check --requirement (Join-Path $RepoRoot "packaging\requirements-release.txt")
        if ($LASTEXITCODE -ne 0) { throw "Could not install pinned release dependencies" }
    }
    if (-not (Test-ReleaseVenv -PythonExecutable $venvPython -PinnedVersion $base.PinnedVersion -Pins $pins)) {
        throw "Release venv does not match packaging\requirements-release.txt after installation"
    }
    Write-Host ("==> Release venv ready: {0}" -f $venvPython)
    return @{
        Root            = $venvRoot
        Executable      = $venvPython
        PinnedVersion   = $base.PinnedVersion
        BaseRuntimeRoot = Split-Path -Parent $base.Executable
        Pins            = $pins
    }
}

function Get-ControlledReleaseBuildPath {
    param([string]$ReleaseVenvRoot)
    $systemRoot = [Environment]::GetEnvironmentVariable("SystemRoot", "Machine")
    if (-not $systemRoot) { $systemRoot = $env:SystemRoot }
    if (-not $systemRoot) { throw "Could not resolve Windows SystemRoot for release PATH" }
    $entries = @(
        (Join-Path $ReleaseVenvRoot "Scripts"),
        $ReleaseVenvRoot,
        (Join-Path $systemRoot "System32"),
        $systemRoot
    ) | Where-Object { $_ -and (Test-Path $_) } | Select-Object -Unique
    if ($entries.Count -lt 4) { throw "Controlled release PATH is missing a required venv or Windows directory" }
    return ($entries -join ";")
}

function Get-BuildDependencyVersions {
    param([string]$PythonExecutable)
    $pythonVersion = (& $PythonExecutable -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}')").Trim()
    if ($LASTEXITCODE -ne 0) { throw "Failed to read python --version" }
    $pyinstallerVersion = (& $PythonExecutable -c "import PyInstaller; print(PyInstaller.__version__)").Trim()
    if ($LASTEXITCODE -ne 0) { throw "Failed to read PyInstaller version" }
    $pysideVersion = (& $PythonExecutable -c "import PySide6; print(PySide6.__version__)").Trim()
    if ($LASTEXITCODE -ne 0) { throw "Failed to read PySide6 version" }
    return @{
        python_version     = $pythonVersion
        pyinstaller_version = $pyinstallerVersion
        pyside6_version    = $pysideVersion
    }
}
