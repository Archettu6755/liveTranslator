[CmdletBinding()]
param(
    [switch]$Force
)

$ErrorActionPreference = 'Stop'

$configDirectory = Join-Path $env:LOCALAPPDATA 'LiveTranslator'
$configPath = Join-Path $configDirectory 'config.toml'
$environmentPath = Join-Path $configDirectory '.env'

New-Item -ItemType Directory -Path $configDirectory -Force | Out-Null

if ($Force -or -not (Test-Path -LiteralPath $configPath)) {
    Copy-Item -LiteralPath (Join-Path $PSScriptRoot 'config.example.toml') -Destination $configPath
}

if ($Force -or -not (Test-Path -LiteralPath $environmentPath)) {
    Copy-Item -LiteralPath (Join-Path $PSScriptRoot '.env.example') -Destination $environmentPath
}

$identity = [System.Security.Principal.WindowsIdentity]::GetCurrent()
$fileSecurity = [System.Security.AccessControl.FileSecurity]::new()
$fileSecurity.SetOwner($identity.User)
$fileSecurity.SetAccessRuleProtection($true, $false)
$accessRule = [System.Security.AccessControl.FileSystemAccessRule]::new(
    $identity.User,
    [System.Security.AccessControl.FileSystemRights]::FullControl,
    [System.Security.AccessControl.AccessControlType]::Allow
)
$fileSecurity.AddAccessRule($accessRule)
Set-Acl -LiteralPath $environmentPath -AclObject $fileSecurity

$verifiedAcl = Get-Acl -LiteralPath $environmentPath
$unexpectedRules = @(
    $verifiedAcl.Access | Where-Object {
        $_.IdentityReference.Translate(
            [System.Security.Principal.SecurityIdentifier]
        ).Value -ne $identity.User.Value -or
        $_.AccessControlType -ne [System.Security.AccessControl.AccessControlType]::Allow
    }
)
if (-not $verifiedAcl.AreAccessRulesProtected -or $unexpectedRules.Count -ne 0) {
    throw "Could not restrict access to $environmentPath"
}

Write-Output "Configuration directory: $configDirectory"
Write-Output 'Edit config.toml and .env before starting LiveTranslator.exe.'
