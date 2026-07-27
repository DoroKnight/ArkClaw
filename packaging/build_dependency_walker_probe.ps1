[CmdletBinding()]
param(
    [switch]$ConfirmProbeBuild
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

if (-not $ConfirmProbeBuild) {
    Write-Output "safe_code=dependency_walker_probe_build_disabled"
    exit 0
}

$RequiredMsvcToolsVersion = "14.44.35207"
$RepositoryRoot = [System.IO.Path]::GetFullPath(
    (Join-Path -Path $PSScriptRoot -ChildPath "..")
)
$SmokeDirectory = Join-Path `
    $RepositoryRoot `
    "build\dependency-walker-smoke"
$ProbeSource = Join-Path `
    $RepositoryRoot `
    "packaging\dependency_walker_probe.c"
$DependencySource = Join-Path `
    $RepositoryRoot `
    "packaging\dependency_walker_probe_dependency.c"

function Stop-Safe {
    param(
        [Parameter(Mandatory = $true)]
        [string]$SafeCode
    )

    Write-Output "safe_code=$SafeCode"
    exit 2
}

$VsWhereCandidates = @(
    (Join-Path ${env:ProgramFiles(x86)} `
        "Microsoft Visual Studio\Installer\vswhere.exe"),
    (Join-Path $env:ProgramFiles `
        "Microsoft Visual Studio\Installer\vswhere.exe")
)
$VsWherePath = $VsWhereCandidates |
    Where-Object { $_ -and (Test-Path -LiteralPath $_ -PathType Leaf) } |
    Select-Object -First 1
if (-not $VsWherePath) {
    Stop-Safe -SafeCode "visual_studio_not_found"
}

$SelectedInstallation = $null
$Installations = & $VsWherePath `
    -all `
    -products * `
    -requires Microsoft.VisualStudio.Component.VC.Tools.x86.x64 `
    -property installationPath
if ($LASTEXITCODE -ne 0) {
    Stop-Safe -SafeCode "visual_studio_discovery_failed"
}
foreach ($Installation in $Installations) {
    if (-not $Installation) {
        continue
    }
    $CandidateTools = Join-Path `
        $Installation `
        "VC\Tools\MSVC\$RequiredMsvcToolsVersion\bin\Hostx64\x64"
    if (
        (Test-Path `
            -LiteralPath (Join-Path $CandidateTools "cl.exe") `
            -PathType Leaf) -and
        (Test-Path `
            -LiteralPath (Join-Path $CandidateTools "link.exe") `
            -PathType Leaf) -and
        (Test-Path `
            -LiteralPath (Join-Path $CandidateTools "dumpbin.exe") `
            -PathType Leaf)
    ) {
        $SelectedInstallation = $Installation
        $ToolsDirectory = $CandidateTools
        break
    }
}
if (-not $SelectedInstallation) {
    Stop-Safe -SafeCode "msvc_14_44_not_found"
}

$VcVarsAllPath = Join-Path `
    $SelectedInstallation `
    "VC\Auxiliary\Build\vcvarsall.bat"
$ActivationCommand = (
    '"{0}" amd64 -vcvars_ver=14.44 >nul && set' -f $VcVarsAllPath
)
$EnvironmentLines = & $env:ComSpec /d /s /c $ActivationCommand
if ($LASTEXITCODE -ne 0) {
    Stop-Safe -SafeCode "msvc_environment_activation_failed"
}
foreach ($Line in $EnvironmentLines) {
    $Separator = $Line.IndexOf("=")
    if ($Separator -le 0) {
        continue
    }
    $Name = $Line.Substring(0, $Separator)
    $Value = $Line.Substring($Separator + 1)
    [System.Environment]::SetEnvironmentVariable(
        $Name,
        $Value,
        [System.EnvironmentVariableTarget]::Process
    )
}

$ClPath = Join-Path $ToolsDirectory "cl.exe"
$LinkPath = Join-Path $ToolsDirectory "link.exe"
$DumpbinPath = Join-Path $ToolsDirectory "dumpbin.exe"
foreach ($Tool in @($ClPath, $LinkPath, $DumpbinPath)) {
    if (
        -not [System.IO.Path]::GetDirectoryName($Tool).Equals(
            $ToolsDirectory,
            [System.StringComparison]::OrdinalIgnoreCase
        )
    ) {
        Stop-Safe -SafeCode "msvc_toolchain_mismatch"
    }
}
if (
    -not (Test-Path -LiteralPath $ProbeSource -PathType Leaf) -or
    -not (Test-Path -LiteralPath $DependencySource -PathType Leaf)
) {
    Stop-Safe -SafeCode "dependency_walker_probe_source_missing"
}
if (Test-Path -LiteralPath $SmokeDirectory) {
    if (@(Get-ChildItem -LiteralPath $SmokeDirectory -Force).Count -ne 0) {
        Stop-Safe -SafeCode "dependency_walker_probe_build_occupied"
    }
}
else {
    [void](New-Item -ItemType Directory -Path $SmokeDirectory)
}
if (
    (Get-Item -LiteralPath $SmokeDirectory).Attributes -band
    [System.IO.FileAttributes]::ReparsePoint
) {
    Stop-Safe -SafeCode "dependency_walker_probe_build_path_invalid"
}

$DependencyDll = Join-Path $SmokeDirectory "probe_dependency.dll"
$DependencyLib = Join-Path $SmokeDirectory "probe_dependency.lib"
$DependencyObject = Join-Path $SmokeDirectory "probe_dependency.obj"
$DependencyPdb = Join-Path $SmokeDirectory "probe_dependency.pdb"
$ProbeExe = Join-Path $SmokeDirectory "probe.exe"
$ProbeObject = Join-Path $SmokeDirectory "probe.obj"
$ProbePdb = Join-Path $SmokeDirectory "probe.pdb"
$Marker = Join-Path $SmokeDirectory "probe_executed.marker"

& $ClPath `
    /nologo `
    /W4 `
    /WX `
    /O2 `
    /LD `
    "/Fo$DependencyObject" `
    "/Fe:$DependencyDll" `
    $DependencySource `
    /link `
    "/OUT:$DependencyDll" `
    "/IMPLIB:$DependencyLib" `
    "/PDB:$DependencyPdb" `
    /INCREMENTAL:NO
if ($LASTEXITCODE -ne 0) {
    Stop-Safe -SafeCode "dependency_walker_probe_build_failed"
}

& $ClPath `
    /nologo `
    /W4 `
    /WX `
    /O2 `
    "/Fo$ProbeObject" `
    "/Fe:$ProbeExe" `
    $ProbeSource `
    $DependencyLib `
    /link `
    "/OUT:$ProbeExe" `
    "/PDB:$ProbePdb" `
    /INCREMENTAL:NO
if ($LASTEXITCODE -ne 0) {
    Stop-Safe -SafeCode "dependency_walker_probe_build_failed"
}

$DependencyOutput = (& $DumpbinPath /DEPENDENTS $ProbeExe 2>&1 | Out-String)
if (
    $LASTEXITCODE -ne 0 -or
    $DependencyOutput -notmatch '(?im)^\s*probe_dependency\.dll\s*$'
) {
    Stop-Safe -SafeCode "dependency_walker_probe_dependency_missing"
}
if (Test-Path -LiteralPath $Marker) {
    Stop-Safe -SafeCode "dependency_walker_probe_executed"
}

Write-Output (
    "dependency_walker_probe_built=True " +
    "static_dependency=True probe_executed=False safe_code=none"
)
