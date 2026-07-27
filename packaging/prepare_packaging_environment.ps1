[CmdletBinding()]
param(
    [switch]$ConfirmPrepare
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$RepositoryRoot = [System.IO.Path]::GetFullPath(
    (Join-Path $PSScriptRoot "..")
)
$Target = Join-Path $RepositoryRoot ".venv-packaging"
$DevelopmentPython = Join-Path $RepositoryRoot ".venv\Scripts\python.exe"
$InventoryScript = Join-Path `
    $RepositoryRoot `
    "packaging\packaging_environment_inventory.py"
$Pyproject = Join-Path $RepositoryRoot "pyproject.toml"
$Lock = Join-Path $RepositoryRoot "uv.lock"

function Stop-Safe {
    param([Parameter(Mandatory = $true)][string]$SafeCode)
    Write-Output "safe_code=$SafeCode"
    exit 2
}

if (-not $ConfirmPrepare) {
    Write-Output "safe_code=packaging_environment_prepare_disabled"
    exit 0
}
if (
    -not (Test-Path -LiteralPath $DevelopmentPython -PathType Leaf) -or
    -not (Test-Path -LiteralPath $InventoryScript -PathType Leaf) -or
    -not (Test-Path -LiteralPath $Pyproject -PathType Leaf) -or
    -not (Test-Path -LiteralPath $Lock -PathType Leaf)
) {
    Stop-Safe -SafeCode "packaging_environment_invalid"
}

$UvCommand = Get-Command `
    uv.exe `
    -CommandType Application `
    -ErrorAction SilentlyContinue |
    Select-Object -First 1
if (-not $UvCommand) {
    Stop-Safe -SafeCode "packaging_environment_invalid"
}
$UvPath = [System.IO.Path]::GetFullPath($UvCommand.Source)
$UvVersion = & $UvPath --version
if (
    $LASTEXITCODE -ne 0 -or
    $UvVersion -ne "uv 0.11.2 (02036a8ba 2026-03-26 x86_64-pc-windows-msvc)"
) {
    Stop-Safe -SafeCode "packaging_environment_invalid"
}

$PythonProbe = & $DevelopmentPython -I -c (
    "import json,platform,sys;" +
    "print(json.dumps({'version':platform.python_version()," +
    "'amd64':sys.maxsize>2**32,'compiler':platform.python_compiler()}))"
)
if ($LASTEXITCODE -ne 0) {
    Stop-Safe -SafeCode "packaging_environment_invalid"
}
$PythonInfo = $PythonProbe | ConvertFrom-Json
if (
    $PythonInfo.version -ne "3.13.6" -or
    -not $PythonInfo.amd64 -or
    $PythonInfo.compiler -notmatch "MSC v\.1944"
) {
    Stop-Safe -SafeCode "packaging_environment_invalid"
}

$PyprojectHashBefore = (Get-FileHash -Algorithm SHA256 $Pyproject).Hash
$LockHashBefore = (Get-FileHash -Algorithm SHA256 $Lock).Hash
$env:VIRTUAL_ENV = $Target
$env:PYTHONPATH = $null
$env:PYTHONHOME = $null
$env:UV_OFFLINE = "1"
$env:UV_NO_PYTHON_DOWNLOADS = "1"
$env:PIP_NO_INDEX = "1"

if (Test-Path -LiteralPath $Target) {
    $ExistingPython = Join-Path $Target "Scripts\python.exe"
    if (-not (Test-Path -LiteralPath $ExistingPython -PathType Leaf)) {
        Stop-Safe -SafeCode "packaging_environment_occupied"
    }
    & $ExistingPython -I $InventoryScript --write-inventory
    if ($LASTEXITCODE -ne 0) {
        Stop-Safe -SafeCode "packaging_environment_occupied"
    }
    Write-Output "safe_code=packaging_environment_ready"
    exit 0
}

& $UvPath venv `
    --python $DevelopmentPython `
    --no-python-downloads `
    $Target
if ($LASTEXITCODE -ne 0) {
    Stop-Safe -SafeCode "packaging_environment_offline_sync_failed"
}
& $UvPath sync `
    --active `
    --locked `
    --offline `
    --no-python-downloads `
    --no-dev `
    --extra gui `
    --extra packaging
if ($LASTEXITCODE -ne 0) {
    Stop-Safe -SafeCode "packaging_environment_offline_sync_failed"
}

$PyprojectHashAfter = (Get-FileHash -Algorithm SHA256 $Pyproject).Hash
$LockHashAfter = (Get-FileHash -Algorithm SHA256 $Lock).Hash
if (
    $PyprojectHashBefore -ne $PyprojectHashAfter -or
    $LockHashBefore -ne $LockHashAfter
) {
    Stop-Safe -SafeCode "packaging_environment_invalid"
}

$TargetPython = Join-Path $Target "Scripts\python.exe"
& $TargetPython -I $InventoryScript --write-inventory
if ($LASTEXITCODE -ne 0) {
    Stop-Safe -SafeCode "packaging_environment_invalid"
}
Write-Output "safe_code=packaging_environment_ready"
