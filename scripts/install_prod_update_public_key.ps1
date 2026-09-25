#Requires -Version 5.1
<#
.SYNOPSIS
  Embed the production update public key (exilelens-prod-1) into trust.py.

.DESCRIPTION
  Reads only the public key material produced by create_prod_update_key.ps1.
  Never reads or imports the production private key.
#>
param(
    [Parameter(Mandatory = $true)]
    [string]$PublicKeyPath
)

$ErrorActionPreference = "Stop"
$RepoRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
$resolved = Resolve-Path -LiteralPath $PublicKeyPath
$privateHint = "private.pem"
if ($resolved.Path -match $privateHint) {
    throw "Refusing to use a path that looks like a private key file."
}

$py = Join-Path $RepoRoot ".release-venv\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $py)) {
    $py = "py"
    $args = @("-3.12", (Join-Path $RepoRoot "scripts\install_prod_update_public_key.py"), "--public-key", $resolved.Path)
    & $py @args
}
else {
    & $py (Join-Path $RepoRoot "scripts\install_prod_update_public_key.py") --public-key $resolved.Path
}
if ($LASTEXITCODE -ne 0) { throw "Public key installation failed." }
