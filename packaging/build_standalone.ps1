[CmdletBinding()]
param(
    [switch]$ConfirmBuild,
    [string]$VisualStudioPath
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$RequiredMsvcToolsVersion = "14.44.35207"
$RequiredCompilerVersionPrefix = "19.44."
$RequiredPythonCompiler = "MSC v.1944"
$HostArch = "amd64"
$Arch = "amd64"

$RepositoryRoot = [System.IO.Path]::GetFullPath(
    (Join-Path -Path $PSScriptRoot -ChildPath "..")
)
$PackagingEnvironment = Join-Path $RepositoryRoot ".venv-packaging"
$DevelopmentEnvironment = Join-Path $RepositoryRoot ".venv"
$PythonPath = Join-Path $PackagingEnvironment "Scripts\python.exe"
$DeployPath = Join-Path $PackagingEnvironment "Scripts\pyside6-deploy.exe"
$SpecPath = Join-Path $RepositoryRoot "packaging\pysidedeploy.spec"
$NuitkaCachePath = Join-Path $RepositoryRoot "build\nuitka-cache"
$QtPluginRoot = Join-Path `
    $RepositoryRoot `
    ".venv-packaging\Lib\site-packages\PySide6\plugins"
$RequiredQtPluginFamilies = @("platforms", "styles")
$DependencyWalkerPath = Join-Path `
    $NuitkaCachePath `
    "downloads\depends\x86_64\depends.exe"
$DependencyWalkerCacheValidator = Join-Path `
    $RepositoryRoot `
    "packaging\dependency_walker_cache.py"
$StandaloneBuildController = Join-Path `
    $RepositoryRoot `
    "packaging\standalone_build.py"
$StandaloneArtifactAuditor = Join-Path `
    $RepositoryRoot `
    "packaging\standalone_artifact_audit.py"
$DryRunWorkspace = Join-Path `
    $RepositoryRoot `
    "build\standalone-dry-run"
$DryRunSpecPath = Join-Path $DryRunWorkspace "pysidedeploy.spec"
$DryRunStdoutPath = Join-Path `
    $DryRunWorkspace `
    "pyside6-deploy.stdout.log"
$DryRunStderrPath = Join-Path `
    $DryRunWorkspace `
    "pyside6-deploy.stderr.log"
$ProtectedOutputPaths = @(
    (Join-Path $RepositoryRoot "dist"),
    (Join-Path $RepositoryRoot "packaging\deployment"),
    (Join-Path $RepositoryRoot "build\windows-standalone")
)
$MinimumFreeBytes = 12GB

function Stop-Safe {
    param(
        [Parameter(Mandatory = $true)]
        [string]$SafeCode
    )

    Write-Output "safe_code=$SafeCode"
    exit 2
}

function Find-VisualStudioInstallation {
    param(
        [string]$RequestedPath
    )

    if ($RequestedPath) {
        return [System.IO.Path]::GetFullPath($RequestedPath)
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
        $RequiredExecutables = @("cl.exe", "link.exe", "dumpbin.exe")
        $HasAllTools = $true
        foreach ($Executable in $RequiredExecutables) {
            if (-not (Test-Path `
                -LiteralPath (Join-Path $CandidateTools $Executable) `
                -PathType Leaf)) {
                $HasAllTools = $false
                break
            }
        }
        if ($HasAllTools) {
            return [System.IO.Path]::GetFullPath($Installation)
        }
    }

    Stop-Safe -SafeCode "msvc_14_44_not_found"
}

function Import-MsvcEnvironment {
    param(
        [Parameter(Mandatory = $true)]
        [string]$InstallationPath
    )

    $VcVarsAllPath = Join-Path `
        $InstallationPath `
        "VC\Auxiliary\Build\vcvarsall.bat"
    if (-not (Test-Path -LiteralPath $VcVarsAllPath -PathType Leaf)) {
        Stop-Safe -SafeCode "msvc_environment_script_not_found"
    }

    $ActivationCommand = (
        '"{0}" amd64 -vcvars_ver=14.44 >nul && set' -f $VcVarsAllPath
    )
    $EnvironmentLines = & $env:ComSpec /d /s /c $ActivationCommand
    if ($LASTEXITCODE -ne 0) {
        Stop-Safe -SafeCode "msvc_environment_activation_failed"
    }

    # cmd.exe may emit both PATH and Path. Windows environment names are
    # case-insensitive. Retain the first occurrence for ordinary variables,
    # but select PATH by the exact activated MSVC tool directory so a later,
    # stale mixed-case Path value cannot replace vcvarsall's PATH.
    $ImportedNames = [System.Collections.Generic.HashSet[string]]::new(
        [System.StringComparer]::OrdinalIgnoreCase
    )
    $ActivatedPath = $null
    $ExpectedToolsFragment = (
        "VC\Tools\MSVC\$RequiredMsvcToolsVersion\bin\Hostx64\x64"
    )
    foreach ($Line in $EnvironmentLines) {
        $Separator = $Line.IndexOf("=")
        if ($Separator -le 0) {
            continue
        }
        $Name = $Line.Substring(0, $Separator)
        $Value = $Line.Substring($Separator + 1)
        if (
            $Name.Equals(
                "Path",
                [System.StringComparison]::OrdinalIgnoreCase
            ) -and
            $Value.IndexOf(
                $ExpectedToolsFragment,
                [System.StringComparison]::OrdinalIgnoreCase
            ) -ge 0
        ) {
            $ActivatedPath = $Value
            continue
        }
        if (-not $ImportedNames.Add($Name)) {
            continue
        }
        [System.Environment]::SetEnvironmentVariable(
            $Name,
            $Value,
            [System.EnvironmentVariableTarget]::Process
        )
    }
    if (-not $ActivatedPath) {
        Stop-Safe -SafeCode "msvc_activated_path_missing"
    }
    [System.Environment]::SetEnvironmentVariable(
        "Path",
        $null,
        [System.EnvironmentVariableTarget]::Process
    )
    [System.Environment]::SetEnvironmentVariable(
        "PATH",
        $null,
        [System.EnvironmentVariableTarget]::Process
    )
    [System.Environment]::SetEnvironmentVariable(
        "Path",
        $ActivatedPath,
        [System.EnvironmentVariableTarget]::Process
    )
}

function Resolve-ApplicationPath {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Name
    )

    $Command = Get-Command `
        -Name $Name `
        -CommandType Application `
        -ErrorAction SilentlyContinue |
        Select-Object -First 1
    if (-not $Command) {
        Stop-Safe -SafeCode "msvc_tool_not_found"
    }
    return [System.IO.Path]::GetFullPath($Command.Source)
}

function Confirm-MsvcToolchain {
    param(
        [Parameter(Mandatory = $true)]
        [string]$InstallationPath
    )

    $ExpectedToolsPath = [System.IO.Path]::GetFullPath(
        (Join-Path `
            $InstallationPath `
            "VC\Tools\MSVC\$RequiredMsvcToolsVersion\bin\Hostx64\x64")
    )
    $ClPath = Resolve-ApplicationPath -Name "cl.exe"
    $LinkPath = Resolve-ApplicationPath -Name "link.exe"
    $DumpbinPath = Resolve-ApplicationPath -Name "dumpbin.exe"

    foreach ($ToolPath in @($ClPath, $LinkPath, $DumpbinPath)) {
        $ToolDirectory = [System.IO.Path]::GetDirectoryName($ToolPath)
        if (-not $ToolDirectory.Equals(
            $ExpectedToolsPath,
            [System.StringComparison]::OrdinalIgnoreCase
        )) {
            Stop-Safe -SafeCode "msvc_toolchain_mismatch"
        }
    }
    if ($LinkPath -match '(?i)[\\/]msys(?:64)?[\\/]') {
        Stop-Safe -SafeCode "msys_link_rejected"
    }

    if ($env:VCToolsVersion.TrimEnd("\") -ne $RequiredMsvcToolsVersion) {
        Stop-Safe -SafeCode "msvc_tools_version_mismatch"
    }
    if (
        $env:VSCMD_ARG_HOST_ARCH -ne "x64" -or
        $env:VSCMD_ARG_TGT_ARCH -ne "x64"
    ) {
        Stop-Safe -SafeCode "msvc_architecture_mismatch"
    }

    $PreviousErrorActionPreference = $ErrorActionPreference
    try {
        # cl.exe writes its version banner to stderr and exits without
        # compiling when no source is supplied. Windows PowerShell 5 converts
        # redirected native stderr into ErrorRecord objects when Stop is set.
        $ErrorActionPreference = "Continue"
        $CompilerOutput = (& $ClPath 2>&1 | Out-String)
    }
    finally {
        $ErrorActionPreference = $PreviousErrorActionPreference
    }
    if ($CompilerOutput -notmatch (
        [regex]::Escape($RequiredCompilerVersionPrefix)
    )) {
        Stop-Safe -SafeCode "msvc_compiler_version_mismatch"
    }

    $PythonProbe = @'
import platform
import sys

print(platform.python_compiler())
print(64 if sys.maxsize > 2**32 else 32)
print(platform.architecture()[0])
'@
    $PythonOutput = & $PythonPath -c $PythonProbe
    if ($LASTEXITCODE -ne 0) {
        Stop-Safe -SafeCode "python_toolchain_probe_failed"
    }
    if (
        $PythonOutput.Count -ne 3 -or
        $PythonOutput[0] -notlike "*$RequiredPythonCompiler*" -or
        $PythonOutput[1] -ne "64" -or
        $PythonOutput[2] -ne "64bit"
    ) {
        Stop-Safe -SafeCode "python_toolchain_mismatch"
    }

    Write-Output (
        (
            "toolchain_valid=True msvc_tools_version={0} " +
            "compiler_version=19.44 host_arch={1} arch={2}"
        ) -f $RequiredMsvcToolsVersion, $HostArch, $Arch
    )
}

function ConvertTo-WindowsProcessArgument {
    param(
        [Parameter(Mandatory = $true)]
        [AllowEmptyString()]
        [string]$Value
    )

    if ($Value.Length -gt 0 -and $Value -notmatch '[\s"]') {
        return $Value
    }

    $Builder = [System.Text.StringBuilder]::new()
    [void]$Builder.Append('"')
    $BackslashCount = 0
    foreach ($Character in $Value.ToCharArray()) {
        if ($Character -eq "\") {
            $BackslashCount += 1
            continue
        }
        if ($Character -eq '"') {
            [void]$Builder.Append("\" * (($BackslashCount * 2) + 1))
            [void]$Builder.Append('"')
            $BackslashCount = 0
            continue
        }
        if ($BackslashCount -gt 0) {
            [void]$Builder.Append("\" * $BackslashCount)
            $BackslashCount = 0
        }
        [void]$Builder.Append($Character)
    }
    if ($BackslashCount -gt 0) {
        [void]$Builder.Append("\" * ($BackslashCount * 2))
    }
    [void]$Builder.Append('"')
    return $Builder.ToString()
}

function Invoke-DeployWithClosedInput {
    param(
        [Parameter(Mandatory = $true)]
        [string[]]$Arguments,
        [Parameter(Mandatory = $true)]
        [string]$StandardOutputPath,
        [Parameter(Mandatory = $true)]
        [string]$StandardErrorPath
    )

    $StartInfo = [System.Diagnostics.ProcessStartInfo]::new()
    $StartInfo.FileName = $DeployPath
    $StartInfo.WorkingDirectory = $RepositoryRoot
    $StartInfo.UseShellExecute = $false
    $StartInfo.RedirectStandardInput = $true
    $StartInfo.RedirectStandardOutput = $true
    $StartInfo.RedirectStandardError = $true
    $StartInfo.CreateNoWindow = $true
    $StartInfo.Arguments = (
        $Arguments |
        ForEach-Object { ConvertTo-WindowsProcessArgument -Value $_ }
    ) -join " "

    $Process = [System.Diagnostics.Process]::new()
    $Process.StartInfo = $StartInfo
    if (-not $Process.Start()) {
        Stop-Safe -SafeCode "deployment_process_start_failed"
    }
    $Process.StandardInput.Close()
    $StandardOutputTask = $Process.StandardOutput.ReadToEndAsync()
    $StandardErrorTask = $Process.StandardError.ReadToEndAsync()
    $Process.WaitForExit()
    $StandardOutput = $StandardOutputTask.GetAwaiter().GetResult()
    $StandardError = $StandardErrorTask.GetAwaiter().GetResult()
    $ExitCode = $Process.ExitCode
    $Process.Dispose()

    $Utf8NoBom = [System.Text.UTF8Encoding]::new($false)
    [System.IO.File]::WriteAllText(
        $StandardOutputPath,
        $StandardOutput,
        $Utf8NoBom
    )
    [System.IO.File]::WriteAllText(
        $StandardErrorPath,
        $StandardError,
        $Utf8NoBom
    )
    if ($StandardOutput) {
        [System.Console]::Out.WriteLine($StandardOutput.TrimEnd())
    }
    if ($StandardError) {
        [System.Console]::Error.WriteLine($StandardError.TrimEnd())
    }
    return $ExitCode
}

function Set-PackagingProcessEnvironment {
    $DevelopmentScripts = [System.IO.Path]::GetFullPath(
        (Join-Path $DevelopmentEnvironment "Scripts")
    )
    $PackagingScripts = [System.IO.Path]::GetFullPath(
        (Join-Path $PackagingEnvironment "Scripts")
    )
    $SanitizedPathEntries = @(
        $env:Path -split [System.IO.Path]::PathSeparator |
            Where-Object { $_ } |
            Where-Object {
                try {
                    -not [System.IO.Path]::GetFullPath($_).Equals(
                        $DevelopmentScripts,
                        [System.StringComparison]::OrdinalIgnoreCase
                    )
                }
                catch {
                    $false
                }
            }
    )
    $env:Path = (@($PackagingScripts) + $SanitizedPathEntries) -join (
        [System.IO.Path]::PathSeparator
    )
    $env:VIRTUAL_ENV = $PackagingEnvironment
    $env:PYTHONPATH = $null
    $env:PYTHONHOME = $null
}

if (-not (Test-Path -LiteralPath $PythonPath -PathType Leaf)) {
    Stop-Safe -SafeCode "python_environment_not_found"
}
if (-not (Test-Path -LiteralPath $DeployPath -PathType Leaf)) {
    Stop-Safe -SafeCode "pyside_deploy_not_found"
}
if (-not (Test-Path -LiteralPath $SpecPath -PathType Leaf)) {
    Stop-Safe -SafeCode "deployment_spec_not_found"
}
foreach ($PluginFamily in $RequiredQtPluginFamilies) {
    $PluginFamilyPath = Join-Path $QtPluginRoot $PluginFamily
    if (-not (Test-Path -LiteralPath $PluginFamilyPath -PathType Container)) {
        Stop-Safe -SafeCode "standalone_toolchain_invalid"
    }
}
if (
    -not (Test-Path `
        -LiteralPath (Join-Path $QtPluginRoot "platforms\qwindows.dll") `
        -PathType Leaf)
) {
    Stop-Safe -SafeCode "standalone_toolchain_invalid"
}
if (
    -not (Test-Path `
        -LiteralPath $DependencyWalkerCacheValidator `
        -PathType Leaf)
) {
    Stop-Safe -SafeCode "dependency_walker_cache_validator_missing"
}
if (
    -not (Test-Path `
        -LiteralPath $StandaloneBuildController `
        -PathType Leaf) -or
    -not (Test-Path `
        -LiteralPath $StandaloneArtifactAuditor `
        -PathType Leaf)
) {
    Stop-Safe -SafeCode "standalone_toolchain_invalid"
}
if (Test-Path -LiteralPath $DryRunWorkspace) {
    Stop-Safe -SafeCode "standalone_dry_run_workspace_occupied"
}

$env:NUITKA_CACHE_DIR = $NuitkaCachePath
$env:PIP_NO_INDEX = "1"
$env:PIP_DISABLE_PIP_VERSION_CHECK = "1"
$env:UV_OFFLINE = "1"
$SensitiveEnvironmentPattern = (
    "(?i)(?:API_?KEY|AUTHORIZATION|BEARER|COOKIE|CREDENTIAL|" +
    "PASSWORD|SECRET|TOKEN)"
)
[System.Environment]::GetEnvironmentVariables(
    [System.EnvironmentVariableTarget]::Process
).Keys |
    ForEach-Object { [string]$_ } |
    Where-Object { $_ -match $SensitiveEnvironmentPattern } |
    ForEach-Object {
        [System.Environment]::SetEnvironmentVariable(
            $_,
            $null,
            [System.EnvironmentVariableTarget]::Process
        )
    }
Set-PackagingProcessEnvironment

$NuitkaVersionOutput = & $PythonPath -m nuitka --version
if ($LASTEXITCODE -ne 0) {
    Stop-Safe -SafeCode "nuitka_version_check_failed"
}
if (($NuitkaVersionOutput | Select-Object -First 1) -ne "4.0") {
    Stop-Safe -SafeCode "nuitka_version_mismatch"
}

if (-not $ConfirmBuild) {
    & $PythonPath `
        $StandaloneBuildController `
        --prepare-dry-run-workspace
    if ($LASTEXITCODE -ne 0) {
        exit 2
    }
    $DeployArguments = @(
        "--config-file",
        $DryRunSpecPath,
        "--mode",
        "standalone",
        "--nuitka-version",
        "4.0",
        "--dry-run"
    )
    $DeployExitCode = 2
    $DeployInvocationFailed = $false
    try {
        $DeployExitCode = Invoke-DeployWithClosedInput `
            -Arguments $DeployArguments `
            -StandardOutputPath $DryRunStdoutPath `
            -StandardErrorPath $DryRunStderrPath
    }
    catch {
        $DeployInvocationFailed = $true
    }
    & $PythonPath `
        $StandaloneBuildController `
        --finalize-dry-run-workspace
    if ($LASTEXITCODE -ne 0) {
        exit 2
    }
    if ($DeployInvocationFailed -or $DeployExitCode -ne 0) {
        Stop-Safe -SafeCode "standalone_dry_run_isolation_failed"
    }
    Write-Output (
        "standalone_preflight=True mode=dry_run cache_scope=repository " +
        "stdin_closed=True safe_code=none"
    )
    exit 0
}

$SelectedVisualStudio = Find-VisualStudioInstallation `
    -RequestedPath $VisualStudioPath
Import-MsvcEnvironment -InstallationPath $SelectedVisualStudio
Set-PackagingProcessEnvironment
Confirm-MsvcToolchain -InstallationPath $SelectedVisualStudio

foreach ($ProtectedOutputPath in $ProtectedOutputPaths) {
    if (Test-Path -LiteralPath $ProtectedOutputPath) {
        Stop-Safe -SafeCode "standalone_output_occupied"
    }
}
try {
    $RepositoryDrive = [System.IO.DriveInfo]::new(
        [System.IO.Path]::GetPathRoot($RepositoryRoot)
    )
    if ($RepositoryDrive.AvailableFreeSpace -lt $MinimumFreeBytes) {
        Stop-Safe -SafeCode "standalone_disk_space_insufficient"
    }
}
catch {
    Stop-Safe -SafeCode "standalone_disk_space_insufficient"
}

& $PythonPath $DependencyWalkerCacheValidator --validate-cache
if ($LASTEXITCODE -ne 0) {
    Stop-Safe -SafeCode "standalone_toolchain_invalid"
}

& $PythonPath $StandaloneBuildController --confirm-build
if ($LASTEXITCODE -ne 0) {
    exit 2
}

& $PythonPath $StandaloneArtifactAuditor --confirm-audit
if ($LASTEXITCODE -ne 0) {
    exit 2
}
exit 0
