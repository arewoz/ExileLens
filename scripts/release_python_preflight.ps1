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

function Get-ReleaseLockPins {
    param([string]$RepoRoot)
    # Parses the generated hash lock. This is separate from
    # Get-ReleaseDependencyPins on purpose: the direct requirements file must
    # stay simple `Package==Version` lines, while only the lock understands
    # `\` continuations and `--hash=sha256:...` entries.
    $lock = Join-Path $RepoRoot "packaging\requirements-release.lock"
    if (-not (Test-Path $lock)) {
        throw "Missing hash-locked release requirements: $lock (refresh with: py -3.12 scripts\lock_release_deps.py)"
    }
    $entries = @{}
    $current = $null
    $lineNumber = 0
    foreach ($raw in Get-Content -Path $lock) {
        $lineNumber++
        $text = $raw.Trim()
        if (-not $text -or $text.StartsWith("#")) { continue }
        $continues = $false
        if ($text.EndsWith("\")) {
            $continues = $true
            $text = $text.Substring(0, $text.Length - 1).Trim()
        }
        if (-not $text) { continue }
        if ($null -eq $current) {
            if ($text -notmatch '^([A-Za-z0-9_.-]+)==([A-Za-z0-9_.+!-]+)$') {
                throw "Release lock must use exact package pins, got ${lock}:$lineNumber`: $text"
            }
            $current = $Matches[1].ToLowerInvariant().Replace("_", "-")
            if ($entries.ContainsKey($current)) {
                throw "Release lock has a duplicate entry for ${current} (${lock}:$lineNumber)"
            }
            $entries[$current] = @{ Version = $Matches[2]; Hashes = @() }
            if (-not $continues) { $current = $null }
        }
        else {
            if ($text -notmatch '^--hash=sha256:([0-9a-fA-F]{64})$') {
                throw "Release lock entry $current must list --hash=sha256 pins, got ${lock}:$lineNumber`: $text"
            }
            $entries[$current].Hashes += $Matches[1].ToLowerInvariant()
            if (-not $continues) { $current = $null }
        }
    }
    if ($null -ne $current) { throw "Release lock has a truncated entry for ${current}: $lock" }
    foreach ($name in @($entries.Keys)) {
        if ($entries[$name].Hashes.Count -eq 0) {
            throw "Release lock entry $name==$($entries[$name].Version) has no hashes; --require-hashes cannot verify it"
        }
    }
    if ($entries.Count -eq 0) { throw "Release lock contains no package pins: $lock" }
    return $entries
}

function Assert-ReleaseLockConsistency {
    param([string]$RepoRoot, [hashtable]$Pins)
    # Fail-closed: every direct pin must appear in the hash lock with the same
    # exact version, so the two files cannot silently drift apart.
    $locked = Get-ReleaseLockPins -RepoRoot $RepoRoot
    $errors = @()
    foreach ($name in @($Pins.Keys | Sort-Object)) {
        $key = $name.ToLowerInvariant().Replace("_", "-")
        if (-not $locked.ContainsKey($key)) {
            $errors += "direct pin $name==$($Pins[$name]) is missing from packaging\requirements-release.lock"
        }
        elseif ($locked[$key].Version -ne $Pins[$name]) {
            $errors += "drift: direct pin $name==$($Pins[$name]) does not match lock $name==$($locked[$key].Version) (refresh with: py -3.12 scripts\lock_release_deps.py)"
        }
    }
    if ($errors.Count -gt 0) {
        throw ("Release dependency drift detected:`n  - " + ($errors -join "`n  - "))
    }
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
    Assert-ReleaseLockConsistency -RepoRoot $RepoRoot -Pins $pins

    if (-not (Test-Path $venvPython)) {
        Write-Host "==> Creating isolated release venv: $venvRoot"
        & $base.Executable -m venv $venvRoot
        if ($LASTEXITCODE -ne 0) { throw "Could not create release venv: $venvRoot" }
    }
    if (-not (Test-ReleaseVenv -PythonExecutable $venvPython -PinnedVersion $base.PinnedVersion -Pins $pins)) {
        Write-Host "==> Installing hash-locked release dependencies..."
        & $venvPython -m pip install --disable-pip-version-check --require-hashes --requirement (Join-Path $RepoRoot "packaging\requirements-release.lock")
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
