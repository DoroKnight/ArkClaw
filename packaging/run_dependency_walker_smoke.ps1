[CmdletBinding()]
param(
    [switch]$ConfirmExecution
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

if (-not $ConfirmExecution) {
    Write-Output "safe_code=dependency_walker_execution_disabled"
    exit 0
}

$RepositoryRoot = [System.IO.Path]::GetFullPath(
    (Join-Path -Path $PSScriptRoot -ChildPath "..")
)
$PythonPath = Join-Path $RepositoryRoot ".venv\Scripts\python.exe"
$SmokeScript = Join-Path `
    $RepositoryRoot `
    "packaging\dependency_walker_smoke.py"

if (-not (Test-Path -LiteralPath $PythonPath -PathType Leaf)) {
    Write-Output "safe_code=python_environment_not_found"
    exit 2
}
if (-not (Test-Path -LiteralPath $SmokeScript -PathType Leaf)) {
    Write-Output "safe_code=dependency_walker_smoke_failed"
    exit 2
}

& $PythonPath $SmokeScript --confirm-execution
exit $LASTEXITCODE
