[CmdletBinding()]
param(
    [ValidateSet("Debug", "Release")]
    [string]$Configuration = "Release",
    [string]$SpineSource = "",
    [switch]$PrintSourceManifest,
    [switch]$ValidateSourceOnly,
    [switch]$RunTests
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

function Require-NativeCommand {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Name,
        [Parameter(Mandatory = $true)]
        [string]$FailureCode
    )

    $Command = Get-Command -Name $Name -CommandType Application `
        -ErrorAction SilentlyContinue
    if ($null -eq $Command) {
        Exit-WithCode -Code $FailureCode -ExitCode 1
    }
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

function Get-SourceValidationCode {
    param(
        [Parameter(Mandatory = $true)]
        [string]$SourcePath,
        [switch]$ManagedSource
    )

    $ActualCommit = Get-SourceCommit -SourcePath $SourcePath
    if ($ActualCommit -ne $PinnedManifest.commit) {
        return "spine38_source_commit_mismatch"
    }

    $LicensePath = Join-Path $SourcePath $PinnedManifest.license_filename
    if (-not (Test-Path -LiteralPath $LicensePath -PathType Leaf)) {
        return "spine38_source_license_missing"
    }

    if ($ManagedSource) {
        $null = & git -C $SourcePath symbolic-ref -q HEAD 2>$null
        if ($LASTEXITCODE -eq 0) {
            return "spine38_source_not_detached"
        }

        $Origin = & git -C $SourcePath remote get-url origin 2>$null
        if (
            $LASTEXITCODE -ne 0 -or
            ([string]$Origin).Trim() -ne $PinnedManifest.repository_url
        ) {
            return "spine38_source_origin_mismatch"
        }

        $FetchRefspecs = @(
            & git -C $SourcePath config --get-all remote.origin.fetch 2>$null
        )
        $FetchRefspecExitCode = $LASTEXITCODE
        if ($FetchRefspecExitCode -notin @(0, 1)) {
            return "spine38_source_refspec_mismatch"
        }
        if (
            @($FetchRefspecs | Where-Object {
                -not [string]::IsNullOrWhiteSpace([string]$_)
            }).Count -ne 0
        ) {
            return "spine38_source_refspec_mismatch"
        }
    }

    return $null
}

function Invoke-NativeStage {
    param(
        [Parameter(Mandatory = $true)]
        [string]$FailureCode,
        [Parameter(Mandatory = $true)]
        [scriptblock]$Command
    )

    $PreviousErrorActionPreference = $ErrorActionPreference
    try {
        $ErrorActionPreference = "Continue"
        & $Command
        if ($LASTEXITCODE -ne 0) {
            Exit-WithCode -Code $FailureCode -ExitCode 1
        }
    }
    catch {
        Exit-WithCode -Code $FailureCode -ExitCode 1
    }
    finally {
        $ErrorActionPreference = $PreviousErrorActionPreference
    }
}

if ($PrintSourceManifest) {
    $PinnedManifest | ConvertTo-Json -Compress
    exit 0
}

$HasExplicitSpineSource = $PSBoundParameters.ContainsKey("SpineSource")
if ($HasExplicitSpineSource) {
    if ([string]::IsNullOrWhiteSpace($SpineSource)) {
        Exit-WithCode -Code "spine38_source_missing" -ExitCode 2
    }
    $SpineSource = [System.IO.Path]::GetFullPath($SpineSource)
    if (-not (Test-Path -LiteralPath $SpineSource -PathType Container)) {
        Exit-WithCode -Code "spine38_source_missing" -ExitCode 2
    }
}
else {
    $SpineSource = $DefaultSource
}

Require-NativeCommand -Name "git" -FailureCode "spine38_git_missing"

if ($ValidateSourceOnly) {
    $ValidationCode = Get-SourceValidationCode -SourcePath $SpineSource
    if ($null -ne $ValidationCode) {
        $ValidationExitCode = if (
            $ValidationCode -eq "spine38_source_commit_mismatch"
        ) { 2 } else { 1 }
        Exit-WithCode -Code $ValidationCode -ExitCode $ValidationExitCode
    }
    Write-Output "spine38_source_valid"
    exit 0
}

Require-NativeCommand -Name "cmake" -FailureCode "spine38_cmake_missing"
if ($RunTests) {
    Require-NativeCommand -Name "ctest" -FailureCode "spine38_ctest_missing"
}
[System.IO.Directory]::CreateDirectory($BuildRoot) | Out-Null

if (-not $HasExplicitSpineSource -and -not (Test-Path -LiteralPath $SpineSource)) {
    $TemporarySource = Join-Path $BuildRoot (
        "source.acquire." + [Guid]::NewGuid().ToString("N")
    )
    $AcquisitionFailure = $null
    $SourcePromoted = $false
    $PreviousErrorActionPreference = $ErrorActionPreference
    try {
        $ErrorActionPreference = "Continue"

        Write-Output "spine38_source_init"
        $null = & git init --quiet $TemporarySource
        if ($LASTEXITCODE -ne 0) {
            throw "spine38_source_init_failed"
        }

        $null = & git -C $TemporarySource remote add origin `
            $PinnedManifest.repository_url
        if ($LASTEXITCODE -ne 0) {
            throw "spine38_source_origin_failed"
        }

        $null = & git -C $TemporarySource config --unset-all `
            remote.origin.fetch
        if ($LASTEXITCODE -ne 0) {
            throw "spine38_source_refspec_failed"
        }

        Write-Output "spine38_source_fetch"
        & git -C $TemporarySource fetch `
            --depth 1 `
            --no-tags `
            origin `
            $PinnedManifest.commit
        if ($LASTEXITCODE -ne 0) {
            throw "spine38_source_fetch_failed"
        }

        Write-Output "spine38_source_checkout"
        $null = & git -C $TemporarySource checkout --detach FETCH_HEAD
        if ($LASTEXITCODE -ne 0) {
            throw "spine38_source_checkout_failed"
        }

        $ValidationCode = Get-SourceValidationCode `
            -SourcePath $TemporarySource `
            -ManagedSource
        if ($null -ne $ValidationCode) {
            throw $ValidationCode
        }

        try {
            Move-Item -LiteralPath $TemporarySource -Destination $SpineSource `
                -ErrorAction Stop
        }
        catch {
            throw "spine38_source_promote_failed"
        }
        $SourcePromoted = $true
    }
    catch {
        $AcquisitionFailure = $_.Exception.Message
    }
    finally {
        $ErrorActionPreference = $PreviousErrorActionPreference
        if (-not $SourcePromoted -and (Test-Path -LiteralPath $TemporarySource)) {
            try {
                Remove-Item -LiteralPath $TemporarySource -Recurse -Force `
                    -ErrorAction Stop
            }
            catch {
                $AcquisitionFailure = "spine38_source_cleanup_failed"
            }
        }
    }

    if ($null -ne $AcquisitionFailure) {
        Exit-WithCode -Code $AcquisitionFailure -ExitCode 1
    }
}

$ValidationCode = Get-SourceValidationCode `
    -SourcePath $SpineSource `
    -ManagedSource:(-not $HasExplicitSpineSource)
if ($null -ne $ValidationCode) {
    $ValidationExitCode = if (
        $ValidationCode -eq "spine38_source_commit_mismatch"
    ) { 2 } else { 1 }
    Exit-WithCode -Code $ValidationCode -ExitCode $ValidationExitCode
}

$LicenseSource = Join-Path $SpineSource $PinnedManifest.license_filename

Write-Output "spine38_configure"
Invoke-NativeStage -FailureCode "spine38_configure_failed" -Command {
    & cmake `
        -S $BridgeRoot `
        -B $BuildRoot `
        -G "Visual Studio 18 2026" `
        -A x64 `
        "-DSPINE_RUNTIMES_SOURCE_DIR=$SpineSource"
}

Write-Output "spine38_build"
Invoke-NativeStage -FailureCode "spine38_build_failed" -Command {
    & cmake --build $BuildRoot --config $Configuration `
        --target arkclaw_spine38_bridge
}

$OutputDirectory = Join-Path $BuildRoot $Configuration
$BridgeDll = Join-Path $OutputDirectory "arkclaw_spine38_bridge.dll"
$CopiedLicense = Join-Path $OutputDirectory $PinnedManifest.license_filename
if (-not (Test-Path -LiteralPath $BridgeDll -PathType Leaf)) {
    Exit-WithCode -Code "spine38_bridge_dll_missing" -ExitCode 1
}
if (-not (Test-Path -LiteralPath $CopiedLicense -PathType Leaf)) {
    Exit-WithCode -Code "spine38_build_license_missing" -ExitCode 1
}

if ($RunTests) {
    Write-Output "spine38_test"
    Invoke-NativeStage -FailureCode "spine38_test_failed" -Command {
        & ctest --test-dir $BuildRoot -C $Configuration --output-on-failure
    }
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
