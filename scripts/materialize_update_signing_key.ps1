#Requires -Version 5.1
<#
.SYNOPSIS
  Decode EXILELENS_UPDATE_SIGNING_KEY_B64 into a temp PEM and set EXILELENS_UPDATE_SIGNING_KEY_PATH.

.DESCRIPTION
  Used by release CI. Reads the GitHub Actions secret from the environment variable
  EXILELENS_UPDATE_SIGNING_KEY_B64 (standard base64 of the Ed25519 private key PEM bytes).
  Never prints key material.
#>
param(
    [string]$OutputPath = ""
)

$ErrorActionPreference = "Stop"

$keyB64 = $env:EXILELENS_UPDATE_SIGNING_KEY_B64
if ([string]::IsNullOrWhiteSpace($keyB64)) {
    Write-Host "EXILELENS_UPDATE_SIGNING_KEY_B64 is not set; production signing key path will remain unset."
    exit 0
}

$trimmed = $keyB64.Trim()
try {
    $pemBytes = [Convert]::FromBase64String($trimmed)
}
catch {
    throw "EXILELENS_UPDATE_SIGNING_KEY_B64 is not valid base64."
}

$pemText = [System.Text.Encoding]::UTF8.GetString($pemBytes)
if ($pemText -notmatch 'BEGIN (?:PRIVATE KEY|ENCRYPTED PRIVATE KEY)') {
    throw "Decoded signing secret does not look like a PEM private key."
}

if ([string]::IsNullOrWhiteSpace($OutputPath)) {
    $baseDir = if ($env:RUNNER_TEMP) { $env:RUNNER_TEMP } else { [System.IO.Path]::GetTempPath() }
    $OutputPath = Join-Path $baseDir "exilelens-update-signing-key.pem"
}

[System.IO.File]::WriteAllBytes($OutputPath, $pemBytes)

$acl = Get-Acl -LiteralPath $OutputPath
$acl.SetAccessRuleProtection($true, $false)
$acl.Access | ForEach-Object { $acl.RemoveAccessRule($_) | Out-Null }
$rule = New-Object System.Security.AccessControl.FileSystemAccessRule(
    [System.Security.Principal.WindowsIdentity]::GetCurrent().Name,
    "Read",
    "Allow"
)
$acl.AddAccessRule($rule)
Set-Acl -LiteralPath $OutputPath -AclObject $acl

$env:EXILELENS_UPDATE_SIGNING_KEY_PATH = $OutputPath
if ($env:GITHUB_ENV) {
    "EXILELENS_UPDATE_SIGNING_KEY_PATH=$OutputPath" | Out-File -FilePath $env:GITHUB_ENV -Append -Encoding utf8
}

Write-Host "Update signing key materialized at $OutputPath (PEM contents not logged)."
