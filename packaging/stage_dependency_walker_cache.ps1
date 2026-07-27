[CmdletBinding()]
param(
    [switch]$ConfirmStaging
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

if (-not $ConfirmStaging) {
    Write-Output "safe_code=dependency_walker_staging_disabled"
    exit 0
}

$RepositoryRoot = [System.IO.Path]::GetFullPath(
    (Join-Path -Path $PSScriptRoot -ChildPath "..")
)
$PythonPath = Join-Path $RepositoryRoot ".venv\Scripts\python.exe"
$StagingScript = Join-Path `
    $RepositoryRoot `
    "packaging\dependency_walker_cache.py"

if (-not (Test-Path -LiteralPath $PythonPath -PathType Leaf)) {
    Write-Output "safe_code=python_environment_not_found"
    exit 2
}
if (-not (Test-Path -LiteralPath $StagingScript -PathType Leaf)) {
    Write-Output "safe_code=dependency_walker_staging_failed"
    exit 2
}

& $PythonPath $StagingScript --confirm-staging
exit $LASTEXITCODE
