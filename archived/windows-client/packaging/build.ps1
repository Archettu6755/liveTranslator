[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'

$projectDirectory = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$repositoryDirectory = (Resolve-Path (Join-Path $projectDirectory '..')).Path
$releaseDirectory = Join-Path $projectDirectory 'dist\LiveTranslator'
$artifactDirectory = Join-Path $repositoryDirectory 'artifacts'
$archivePath = Join-Path $artifactDirectory 'LiveTranslator-windows-x64.zip'
$checksumPath = "$archivePath.sha256"
$environmentTemplatePath = Join-Path $projectDirectory '.env.example'
$configTemplatePath = Join-Path $projectDirectory 'config.example.toml'
$noticesPath = Join-Path $projectDirectory 'THIRD_PARTY_NOTICES.md'
$licenseDirectory = Join-Path $projectDirectory 'licenses'

function ConvertTo-NormalizedTemplate([string]$Content) {
    return (($Content -replace "`r`n", "`n") -replace "`r", "`n").TrimEnd(
        [char[]]"`n"
    )
}

$expectedEnvironmentTemplate = @'
# configure.ps1 copies this file to %LOCALAPPDATA%\LiveTranslator\.env.
# Replace the placeholder there. Never add a real key to this template.
LIVE_TRANSLATOR_API_KEY=replace-me
'@
$environmentTemplate = ConvertTo-NormalizedTemplate (
    Get-Content -LiteralPath $environmentTemplatePath -Raw
)
if ($environmentTemplate -cne (ConvertTo-NormalizedTemplate $expectedEnvironmentTemplate)) {
    throw 'The release environment template contains a non-placeholder value.'
}
$expectedConfigTemplate = @'
# configure.ps1 copies this template to %LOCALAPPDATA%\LiveTranslator\config.toml.
# Keep production configuration and API credentials out of the source checkout.
[asr]
# The Windows client accepts loopback ASR endpoints only.
ws_url = "ws://127.0.0.1:9000/v1/asr"
ready_url = "http://127.0.0.1:9000/ready"
connect_timeout_s = 5.0
stop_timeout_s = 5.0

[translation]
# Replace both placeholders. Remote endpoints must use HTTPS.
endpoint = "https://provider.invalid/v1/messages"
model = "replace-with-your-model"
anthropic_version = "2023-06-01"
max_tokens = 256
timeout_s = 4.0

[audio]
# Leave device_index commented to use the default WASAPI loopback device.
# device_index = 0
'@
$configTemplate = ConvertTo-NormalizedTemplate (
    Get-Content -LiteralPath $configTemplatePath -Raw
)
if ($configTemplate -cne (ConvertTo-NormalizedTemplate $expectedConfigTemplate)) {
    throw 'The release configuration template contains unexpected values.'
}
if (-not [Environment]::Is64BitProcess) {
    throw 'The x64 release must be built from 64-bit PowerShell.'
}
$requiredLicenseFiles = @(
    'GPL-3.0-only.txt',
    'LGPL-3.0-only.txt',
    'PSF-LICENSE.txt',
    'PYINSTALLER-COPYING.txt'
)
foreach ($name in $requiredLicenseFiles) {
    if (-not (Test-Path -LiteralPath (Join-Path $licenseDirectory $name) -PathType Leaf)) {
        throw "The source tree is missing required license text: $name"
    }
}

Push-Location $projectDirectory
try {
    $pythonBitness = (& uv run --frozen --group package python -c `
        'import struct; print(struct.calcsize("P") * 8)' | Out-String).Trim()
    if ($LASTEXITCODE -ne 0 -or $pythonBitness -ne '64') {
        throw 'The x64 release requires a 64-bit Python environment.'
    }
    & uv run --frozen --group package python ..\scripts\check_repository.py ..
    if ($LASTEXITCODE -ne 0) {
        throw 'Repository security checks failed.'
    }
    & uv run --frozen --group package pyinstaller --noconfirm --clean `
        packaging/live-translator.spec
    if ($LASTEXITCODE -ne 0) {
        throw 'PyInstaller failed.'
    }
} finally {
    Pop-Location
}

Copy-Item -LiteralPath $configTemplatePath -Destination $releaseDirectory -Force
Copy-Item -LiteralPath $environmentTemplatePath -Destination $releaseDirectory -Force
Copy-Item -LiteralPath (Join-Path $projectDirectory 'README.md') -Destination $releaseDirectory -Force
Copy-Item -LiteralPath $noticesPath -Destination $releaseDirectory -Force
Copy-Item -LiteralPath $licenseDirectory -Destination $releaseDirectory -Recurse -Force
Copy-Item -LiteralPath (Join-Path $PSScriptRoot 'configure.ps1') -Destination $releaseDirectory -Force

$requiredPatterns = @(
    'LiveTranslator.exe',
    'qwindows.dll',
    'qoffscreen.dll',
    'python312.dll',
    'Qt6Core.dll',
    'Qt6Gui.dll',
    'Qt6Widgets.dll',
    'pyside6.abi3.dll',
    'shiboken6.abi3.dll',
    'VCRUNTIME140.dll',
    'VCRUNTIME140_1.dll',
    'MSVCP140.dll',
    'MSVCP140_1.dll',
    'MSVCP140_2.dll',
    '_ssl.pyd',
    'libcrypto-3-x64.dll',
    'libssl-3-x64.dll',
    '_portaudiowpatch*.pyd',
    'soxr_ext*.pyd',
    'cacert.pem'
)
foreach ($pattern in $requiredPatterns) {
    $match = Get-ChildItem -LiteralPath $releaseDirectory -Recurse -File -Filter $pattern |
        Select-Object -First 1
    if ($null -eq $match) {
        throw "Windows release is missing $pattern"
    }
}
$requiredMetadataPatterns = @(
    'anyio-*.dist-info',
    'certifi-*.dist-info',
    'h11-*.dist-info',
    'httpcore-*.dist-info',
    'httpx-*.dist-info',
    'idna-*.dist-info',
    'numpy-*.dist-info',
    'pyaudiowpatch-*.dist-info',
    'pyside6_essentials-*.dist-info',
    'shiboken6-*.dist-info',
    'soxr-*.dist-info',
    'typing_extensions-*.dist-info',
    'websockets-*.dist-info'
)
foreach ($pattern in $requiredMetadataPatterns) {
    $metadata = Get-ChildItem -LiteralPath $releaseDirectory -Recurse -Directory `
        -Filter $pattern | Select-Object -First 1
    if ($null -eq $metadata) {
        throw "Windows release is missing third-party metadata: $pattern"
    }
    $license = Get-ChildItem -LiteralPath $metadata.FullName -Recurse -File |
        Where-Object { $_.Name -match '(?i)(license|copying|notice)' } |
        Select-Object -First 1
    if ($null -eq $license) {
        throw "Windows release is missing a license notice in $($metadata.Name)"
    }
}

$forbiddenNames = @('.env', 'config.toml', 'credentials.json')
$forbiddenExtensions = @(
    '.bin',
    '.ckpt',
    '.engine',
    '.gguf',
    '.key',
    '.log',
    '.onnx',
    '.p12',
    '.pem',
    '.pfx',
    '.pt',
    '.pth',
    '.safetensors'
)
$pemFiles = @(Get-ChildItem -LiteralPath $releaseDirectory -Recurse -File -Filter '*.pem')
$caBundles = @($pemFiles | Where-Object { $_.Name -eq 'cacert.pem' })
if ($caBundles.Count -ne 1) {
    throw 'Windows release must contain exactly one certifi cacert.pem file.'
}
$caBundleText = Get-Content -LiteralPath $caBundles[0].FullName -Raw
if (
    $caBundleText -notmatch '-----BEGIN CERTIFICATE-----' -or
    $caBundleText -match '-----BEGIN .*PRIVATE KEY-----'
) {
    throw 'The bundled cacert.pem is not a certificate-only CA bundle.'
}
$forbiddenFiles = @(
    Get-ChildItem -LiteralPath $releaseDirectory -Recurse -File | Where-Object {
        $extension = $_.Extension.ToLowerInvariant()
        $normalizedName = $_.Name.ToLowerInvariant()
        $_.Name -in $forbiddenNames -or
        ($normalizedName.StartsWith('.env') -and $normalizedName -ne '.env.example') -or
        $normalizedName -match '\.log(?:\.\d+)?$' -or
        ($extension -in $forbiddenExtensions -and $extension -ne '.pem') -or
        ($extension -eq '.pem' -and $_.FullName -ne $caBundles[0].FullName)
    }
)
if ($forbiddenFiles.Count -ne 0) {
    throw "Windows release contains a forbidden credential file: $($forbiddenFiles[0].FullName)"
}

function Invoke-FrozenSelfTest([string]$PlatformName) {
    $variableNames = @(
        'PATH',
        'PYTHONHOME',
        'PYTHONPATH',
        'VIRTUAL_ENV',
        'QT_PLUGIN_PATH',
        'QT_QPA_PLATFORM_PLUGIN_PATH',
        'QML2_IMPORT_PATH',
        'SSL_CERT_FILE',
        'REQUESTS_CA_BUNDLE',
        'QT_QPA_PLATFORM'
    )
    $savedEnvironment = @{}
    foreach ($name in $variableNames) {
        $savedEnvironment[$name] = [Environment]::GetEnvironmentVariable($name, 'Process')
    }
    try {
        foreach ($name in $variableNames) {
            [Environment]::SetEnvironmentVariable($name, $null, 'Process')
        }
        $systemRoot = [Environment]::GetEnvironmentVariable('SystemRoot', 'Process')
        if (-not $systemRoot) {
            throw 'SystemRoot is unavailable for the isolated self-test.'
        }
        $cleanPath = @(
            (Join-Path $systemRoot 'System32'),
            $systemRoot,
            (Join-Path $systemRoot 'System32\Wbem')
        ) -join ';'
        [Environment]::SetEnvironmentVariable('PATH', $cleanPath, 'Process')
        [Environment]::SetEnvironmentVariable('QT_QPA_PLATFORM', $PlatformName, 'Process')
        $process = Start-Process `
            -FilePath (Join-Path $releaseDirectory 'LiveTranslator.exe') `
            -ArgumentList '--self-test' `
            -WorkingDirectory $releaseDirectory `
            -WindowStyle Hidden `
            -PassThru
        try {
            if (-not $process.WaitForExit(30000)) {
                $process.Kill()
                $process.WaitForExit()
                throw "Frozen client $PlatformName self-test exceeded 30 seconds."
            }
            if ($process.ExitCode -ne 0) {
                throw "Frozen client $PlatformName self-test failed with exit code $($process.ExitCode)"
            }
        } finally {
            $process.Dispose()
        }
    } finally {
        foreach ($name in $variableNames) {
            [Environment]::SetEnvironmentVariable(
                $name,
                $savedEnvironment[$name],
                'Process'
            )
        }
    }
}

Invoke-FrozenSelfTest 'offscreen'
Invoke-FrozenSelfTest 'windows'

foreach ($name in $requiredLicenseFiles) {
    $packagedLicense = Join-Path (Join-Path $releaseDirectory 'licenses') $name
    if (-not (Test-Path -LiteralPath $packagedLicense -PathType Leaf)) {
        throw "Windows release is missing required license text: $name"
    }
}
$lgplText = Get-Content -LiteralPath (
    Join-Path $releaseDirectory 'licenses\LGPL-3.0-only.txt'
) -Raw
$gplText = Get-Content -LiteralPath (
    Join-Path $releaseDirectory 'licenses\GPL-3.0-only.txt'
) -Raw
$pythonLicenseText = Get-Content -LiteralPath (
    Join-Path $releaseDirectory 'licenses\PSF-LICENSE.txt'
) -Raw
if (
    $lgplText -notmatch 'GNU LESSER GENERAL PUBLIC LICENSE' -or
    $gplText -notmatch 'GNU GENERAL PUBLIC LICENSE' -or
    $pythonLicenseText -notmatch 'PYTHON SOFTWARE FOUNDATION LICENSE VERSION 2'
) {
    throw 'A required packaged license text is invalid.'
}

$configurationTestRoot = Join-Path (
    [IO.Path]::GetTempPath()
) "live-translator-config-test-$([Guid]::NewGuid().ToString('N'))"
$savedLocalAppData = [Environment]::GetEnvironmentVariable('LOCALAPPDATA', 'Process')
$savedPSModulePath = [Environment]::GetEnvironmentVariable('PSModulePath', 'Process')
try {
    New-Item -ItemType Directory -Path $configurationTestRoot | Out-Null
    [Environment]::SetEnvironmentVariable('LOCALAPPDATA', $configurationTestRoot, 'Process')
    [Environment]::SetEnvironmentVariable('PSModulePath', $null, 'Process')
    $windowsPowerShell = Join-Path $env:SystemRoot `
        'System32\WindowsPowerShell\v1.0\powershell.exe'
    $configurationScript = Join-Path $releaseDirectory 'configure.ps1'
    $configurationArguments = @(
        '-NoLogo',
        '-NoProfile',
        '-NonInteractive',
        '-ExecutionPolicy',
        'Bypass',
        '-File',
        "`"$configurationScript`""
    ) -join ' '
    $configurationStandardOutput = Join-Path $configurationTestRoot 'stdout.txt'
    $configurationStandardError = Join-Path $configurationTestRoot 'stderr.txt'
    $configurationProcess = Start-Process `
        -FilePath $windowsPowerShell `
        -ArgumentList $configurationArguments `
        -WindowStyle Hidden `
        -RedirectStandardOutput $configurationStandardOutput `
        -RedirectStandardError $configurationStandardError `
        -PassThru
    try {
        if (-not $configurationProcess.WaitForExit(30000)) {
            $configurationProcess.Kill()
            $configurationProcess.WaitForExit()
            throw 'configure.ps1 exceeded 30 seconds under Windows PowerShell.'
        }
        if ($configurationProcess.ExitCode -ne 0) {
            $configurationError = Get-Content `
                -LiteralPath $configurationStandardError `
                -Raw `
                -ErrorAction SilentlyContinue
            throw (
                "configure.ps1 failed with exit code " +
                "$($configurationProcess.ExitCode): $configurationError"
            )
        }
    } finally {
        $configurationProcess.Dispose()
    }
    $configuredDirectory = Join-Path $configurationTestRoot 'LiveTranslator'
    $configuredEnvironment = ConvertTo-NormalizedTemplate (
        Get-Content -LiteralPath (Join-Path $configuredDirectory '.env') -Raw
    )
    $configuredConfig = ConvertTo-NormalizedTemplate (
        Get-Content -LiteralPath (Join-Path $configuredDirectory 'config.toml') -Raw
    )
    if (
        $configuredEnvironment -cne (
            ConvertTo-NormalizedTemplate $expectedEnvironmentTemplate
        ) -or
        $configuredConfig -cne (ConvertTo-NormalizedTemplate $expectedConfigTemplate)
    ) {
        throw 'configure.ps1 did not create the expected local templates.'
    }
} finally {
    [Environment]::SetEnvironmentVariable('LOCALAPPDATA', $savedLocalAppData, 'Process')
    [Environment]::SetEnvironmentVariable('PSModulePath', $savedPSModulePath, 'Process')
    if ([IO.Directory]::Exists($configurationTestRoot)) {
        [IO.Directory]::Delete($configurationTestRoot, $true)
    }
}

New-Item -ItemType Directory -Path $artifactDirectory -Force | Out-Null
Compress-Archive -LiteralPath $releaseDirectory -DestinationPath $archivePath -CompressionLevel Optimal -Force
$checksum = (Get-FileHash -LiteralPath $archivePath -Algorithm SHA256).Hash.ToLowerInvariant()
Set-Content -LiteralPath $checksumPath -Value "$checksum  $(Split-Path $archivePath -Leaf)" -Encoding ascii

Write-Output "Created $archivePath"
Write-Output "SHA256 $checksum"
