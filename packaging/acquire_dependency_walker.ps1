[CmdletBinding()]
param(
    [switch]$ConfirmDownload
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$DependencyWalkerUrl = "https://dependencywalker.com/depends22_x64.zip"
$ExpectedScheme = "https"
$ExpectedHost = "dependencywalker.com"
$ExpectedPath = "/depends22_x64.zip"

if (-not $ConfirmDownload) {
    Write-Output "safe_code=dependency_walker_download_disabled"
    exit 0
}

$Uri = [System.Uri]::new($DependencyWalkerUrl)
if (
    -not $Uri.Scheme.Equals(
        $ExpectedScheme,
        [System.StringComparison]::Ordinal
    ) -or
    -not $Uri.Host.Equals(
        $ExpectedHost,
        [System.StringComparison]::Ordinal
    ) -or
    $Uri.AbsolutePath -ne $ExpectedPath -or
    $Uri.Authority -ne $ExpectedHost -or
    $Uri.UserInfo -or
    $Uri.Query -or
    $Uri.Fragment
) {
    Write-Output "safe_code=dependency_walker_url_rejected"
    exit 2
}

$RepositoryRoot = [System.IO.Path]::GetFullPath(
    (Join-Path -Path $PSScriptRoot -ChildPath "..")
)
$PythonPath = Join-Path $RepositoryRoot ".venv\Scripts\python.exe"
$AuditScriptPath = Join-Path `
    $RepositoryRoot `
    "packaging\dependency_walker_quarantine.py"

if (-not (Test-Path -LiteralPath $PythonPath -PathType Leaf)) {
    Write-Output "safe_code=python_environment_not_found"
    exit 2
}
if (-not (Test-Path -LiteralPath $AuditScriptPath -PathType Leaf)) {
    Write-Output "safe_code=dependency_walker_audit_script_not_found"
    exit 2
}

& $PythonPath $AuditScriptPath --confirm-download
exit $LASTEXITCODE
