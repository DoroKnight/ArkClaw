[CmdletBinding()]
param(
    [switch]$ConfirmExtraction
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

if (-not $ConfirmExtraction) {
    Write-Output "safe_code=dependency_walker_extraction_disabled"
    exit 0
}

$RepositoryRoot = [System.IO.Path]::GetFullPath(
    (Join-Path -Path $PSScriptRoot -ChildPath "..")
)
$PythonPath = Join-Path $RepositoryRoot ".venv\Scripts\python.exe"
$AuditScriptPath = Join-Path `
    $RepositoryRoot `
    "packaging\dependency_walker_binary_audit.py"

if (-not (Test-Path -LiteralPath $PythonPath -PathType Leaf)) {
    Write-Output "safe_code=python_environment_not_found"
    exit 2
}
if (-not (Test-Path -LiteralPath $AuditScriptPath -PathType Leaf)) {
    Write-Output "safe_code=dependency_walker_binary_audit_script_not_found"
    exit 2
}

& $PythonPath $AuditScriptPath --confirm-extraction
exit $LASTEXITCODE
