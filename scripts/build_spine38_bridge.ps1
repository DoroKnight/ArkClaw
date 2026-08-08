[CmdletBinding()]
param(
    [ValidateSet("Debug", "Release")]
    [string]$Configuration = "Release",
    [string]$SpineSource = "",
    [switch]$PrintSourceManifest,
    [switch]$ValidateSourceOnly
)

$ErrorActionPreference = "Stop"
$env:TrackFileAccess = "false"

$RepositoryRoot = [System.IO.Path]::GetFullPath(
    (Join-Path $PSScriptRoot "..")
)
$BridgeRoot = Join-Path $RepositoryRoot "native\spine38_bridge"
$LockPath = Join-Path $BridgeRoot "spine-runtimes.lock.json"
$BuildRoot = Join-Path $RepositoryRoot "build\spine38"
$DefaultSource = Join-Path $BuildRoot "source"
$Manifest = Get-Content -Raw -LiteralPath $LockPath | ConvertFrom-Json
$PinnedManifest = [ordered]@{
    repository_url = [string]$Manifest.repository_url
    commit = [string]$Manifest.commit
    runtime_data_version = [string]$Manifest.runtime_data_version
    license_filename = [string]$Manifest.license_filename
}

if ($PrintSourceManifest) {
    $PinnedManifest | ConvertTo-Json -Compress
    exit 0
}

if ([string]::IsNullOrWhiteSpace($SpineSource)) {
    $SpineSource = $DefaultSource
}
$SpineSource = [System.IO.Path]::GetFullPath($SpineSource)

function Exit-WithCode {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Code,
        [Parameter(Mandatory = $true)]
        [int]$ExitCode
    )

    Write-Output $Code
    exit $ExitCode
}

function Get-SourceCommit {
    param(
        [Parameter(Mandatory = $true)]
        [string]$SourcePath
    )

    if (-not (Test-Path -LiteralPath (Join-Path $SourcePath ".git"))) {
        return $null
    }
    $ErrorActionPreference = "SilentlyContinue"
    $Commit = & git -C $SourcePath rev-parse HEAD 2>$null
    if ($LASTEXITCODE -ne 0) {
        return $null
    }
    return ([string]$Commit).Trim()
}

if ($ValidateSourceOnly) {
    $ActualCommit = Get-SourceCommit -SourcePath $SpineSource
    if ($ActualCommit -ne $PinnedManifest.commit) {
        Exit-WithCode -Code "spine38_source_commit_mismatch" -ExitCode 2
    }
    Write-Output "spine38_source_valid"
    exit 0
}

[System.IO.Directory]::CreateDirectory($BuildRoot) | Out-Null
if (-not (Test-Path -LiteralPath $SpineSource)) {
    Write-Output "spine38_source_clone"
    & git clone `
        --depth 1 `
        --branch $PinnedManifest.runtime_data_version `
        --single-branch `
        --no-checkout `
        $PinnedManifest.repository_url `
        $SpineSource
    if ($LASTEXITCODE -ne 0) {
        Exit-WithCode -Code "spine38_source_clone_failed" -ExitCode 1
    }

    $null = & git -C $SpineSource rev-parse --verify "$($PinnedManifest.commit)^{commit}" 2>$null
    if ($LASTEXITCODE -ne 0) {
        Write-Output "spine38_source_fetch"
        & git -C $SpineSource fetch --depth 1 origin $PinnedManifest.commit
        if ($LASTEXITCODE -ne 0) {
            Exit-WithCode -Code "spine38_source_fetch_failed" -ExitCode 1
        }
    }

    & git -C $SpineSource checkout --detach $PinnedManifest.commit
    if ($LASTEXITCODE -ne 0) {
        Exit-WithCode -Code "spine38_source_checkout_failed" -ExitCode 1
    }
}

$ActualCommit = Get-SourceCommit -SourcePath $SpineSource
if ($ActualCommit -ne $PinnedManifest.commit) {
    Exit-WithCode -Code "spine38_source_commit_mismatch" -ExitCode 2
}

$LicenseSource = Join-Path $SpineSource $PinnedManifest.license_filename
if (-not (Test-Path -LiteralPath $LicenseSource -PathType Leaf)) {
    Exit-WithCode -Code "spine38_source_license_missing" -ExitCode 1
}

Write-Output "spine38_configure"
& cmake `
    -S $BridgeRoot `
    -B $BuildRoot `
    -G "Visual Studio 18 2026" `
    -A x64 `
    "-DSPINE_RUNTIMES_SOURCE_DIR=$SpineSource"
if ($LASTEXITCODE -ne 0) {
    Exit-WithCode -Code "spine38_configure_failed" -ExitCode 1
}

Write-Output "spine38_build"
& cmake --build $BuildRoot --config $Configuration --target sjtuclaw_spine38_bridge
if ($LASTEXITCODE -ne 0) {
    Exit-WithCode -Code "spine38_build_failed" -ExitCode 1
}

$OutputDirectory = Join-Path $BuildRoot $Configuration
$BridgeDll = Join-Path $OutputDirectory "sjtuclaw_spine38_bridge.dll"
$CopiedLicense = Join-Path $OutputDirectory $PinnedManifest.license_filename
if (-not (Test-Path -LiteralPath $BridgeDll -PathType Leaf)) {
    Exit-WithCode -Code "spine38_bridge_dll_missing" -ExitCode 1
}
if (-not (Test-Path -LiteralPath $CopiedLicense -PathType Leaf)) {
    Exit-WithCode -Code "spine38_build_license_missing" -ExitCode 1
}

$BuildManifest = [ordered]@{
    commit = $PinnedManifest.commit
    configuration = $Configuration
    architecture = "x64"
    bridge_abi = 1
}
$BuildManifestPath = Join-Path $OutputDirectory "spine38-build-manifest.json"
$BuildManifestJson = $BuildManifest | ConvertTo-Json -Compress
[System.IO.File]::WriteAllText(
    $BuildManifestPath,
    $BuildManifestJson + [Environment]::NewLine,
    [System.Text.UTF8Encoding]::new($false)
)
Write-Output "spine38_build_complete"
