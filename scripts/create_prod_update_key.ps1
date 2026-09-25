#Requires -Version 5.1
<#
.SYNOPSIS
  Generate a production Ed25519 update signing key pair (exilelens-prod-1).

.DESCRIPTION
  Creates PKCS#8 PEM private key material and a raw 32-byte public key (base64) compatible
  with src/exilelens/app/updates/trust.py and scripts/sign_update_manifest.py.

  Private key files are written outside the repository by default. Private key bytes are
  never written to the console.

.PARAMETER OutputDir
  Directory for key material (default: %USERPROFILE%\.exilelens\signing\exilelens-prod-1).

.PARAMETER PythonExe
  Python interpreter with cryptography installed (default: repo .release-venv or py -3.12).
#>
param(
    [string]$OutputDir = "",
    [string]$PythonExe = ""
)

$ErrorActionPreference = "Stop"
$RepoRoot = Resolve-Path (Join-Path $PSScriptRoot "..")

if ([string]::IsNullOrWhiteSpace($OutputDir)) {
    $OutputDir = Join-Path $env:USERPROFILE ".exilelens\signing\exilelens-prod-1"
}
$OutputDir = [System.IO.Path]::GetFullPath($OutputDir)
$repoRootNorm = [System.IO.Path]::GetFullPath($RepoRoot.Path)
if ($OutputDir.StartsWith($repoRootNorm, [StringComparison]::OrdinalIgnoreCase)) {
    throw "OutputDir must be outside the repository. Use: $env:USERPROFILE\.exilelens\signing\exilelens-prod-1"
}

$pyArgs = @()
if ([string]::IsNullOrWhiteSpace($PythonExe)) {
    $venvPy = Join-Path $RepoRoot ".release-venv\Scripts\python.exe"
    if (Test-Path -LiteralPath $venvPy) {
        $PythonExe = $venvPy
    }
    else {
        $PythonExe = "py"
        $pyArgs = @("-3.12")
    }
}

New-Item -ItemType Directory -Force -Path $OutputDir | Out-Null

$privatePem = Join-Path $OutputDir "exilelens-prod-1-private.pem"
$publicB64 = Join-Path $OutputDir "exilelens-prod-1-public.b64"
$secretB64 = Join-Path $OutputDir "exilelens-prod-1-github-secret.b64.txt"
$metaJson = Join-Path $OutputDir "exilelens-prod-1-key-metadata.json"

$generator = @'
import base64
import json
import sys
from pathlib import Path

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

out = Path(sys.argv[1])
private_pem = out / "exilelens-prod-1-private.pem"
public_b64 = out / "exilelens-prod-1-public.b64"
secret_b64 = out / "exilelens-prod-1-github-secret.b64.txt"
meta = out / "exilelens-prod-1-key-metadata.json"

key = Ed25519PrivateKey.generate()
pem_bytes = key.private_bytes(
    encoding=serialization.Encoding.PEM,
    format=serialization.PrivateFormat.PKCS8,
    encryption_algorithm=serialization.NoEncryption(),
)
private_pem.write_bytes(pem_bytes)
raw_pub = key.public_key().public_bytes(
    encoding=serialization.Encoding.Raw,
    format=serialization.PublicFormat.Raw,
)
public_b64.write_text(base64.b64encode(raw_pub).decode("ascii") + "\n", encoding="utf-8")
secret_b64.write_text(base64.b64encode(pem_bytes).decode("ascii") + "\n", encoding="utf-8")
meta.write_text(
    json.dumps(
        {
            "signing_key_id": "exilelens-prod-1",
            "algorithm": "Ed25519",
            "private_key_format": "PKCS8 PEM (no encryption)",
            "public_key_format": "raw 32-byte Ed25519 public key, standard base64",
            "github_actions_secret_name": "EXILELENS_UPDATE_SIGNING_KEY_B64",
            "github_actions_secret_value": "contents of exilelens-prod-1-github-secret.b64.txt (single line, no PEM headers)",
        },
        indent=2,
    )
    + "\n",
    encoding="utf-8",
)
'@

$genPath = Join-Path $env:TEMP "exilelens_gen_prod_key_$([Guid]::NewGuid().ToString('N')).py"
Set-Content -LiteralPath $genPath -Value $generator -Encoding utf8
try {
    if ($pyArgs) {
        & $PythonExe @pyArgs $genPath $OutputDir
    }
    else {
        & $PythonExe $genPath $OutputDir
    }
    if ($LASTEXITCODE -ne 0) {
        throw "Key generation failed (exit $LASTEXITCODE). Install cryptography in the release venv or run scripts/lock_release_deps.py prerequisites."
    }
}
finally {
    Remove-Item -LiteralPath $genPath -Force -ErrorAction SilentlyContinue
}

foreach ($path in @($privatePem, $publicB64, $secretB64, $metaJson)) {
    if (-not (Test-Path -LiteralPath $path)) {
        throw "Expected output file is missing: $path"
    }
}

$acl = Get-Acl -LiteralPath $privatePem
$acl.SetAccessRuleProtection($true, $false)
$acl.Access | ForEach-Object { $acl.RemoveAccessRule($_) | Out-Null }
$rule = New-Object System.Security.AccessControl.FileSystemAccessRule(
    [System.Security.Principal.WindowsIdentity]::GetCurrent().Name,
    "Read",
    "Allow"
)
$acl.AddAccessRule($rule)
Set-Acl -LiteralPath $privatePem -AclObject $acl

Write-Host "Production update signing key pair generated (exilelens-prod-1)."
Write-Host "  Private PEM:     $privatePem"
Write-Host "  Public key b64:  $publicB64"
Write-Host "  GitHub secret:   $secretB64  -> EXILELENS_UPDATE_SIGNING_KEY_B64"
Write-Host "  Metadata:        $metaJson"
Write-Host ""
Write-Host "Next: install the public key into the app trust store:"
Write-Host "  powershell -File scripts\install_prod_update_public_key.ps1 -PublicKeyPath `"$publicB64`""
