[CmdletBinding()]
param(
    [switch]$Console,
    [switch]$ValidateOnly
)

$ErrorActionPreference = 'Stop'

$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
Set-Location $projectRoot

$env:PYTHONPATH = (Resolve-Path (Join-Path $projectRoot 'src')).Path
Remove-Item Env:ARKCLAW_SPINE38_BRIDGE_DLL -ErrorAction SilentlyContinue
Remove-Item Env:ARKCLAW_PET_ROLE_MANIFEST -ErrorAction SilentlyContinue
Remove-Item Env:ARKCLAW_SPINE38_ASSET_ROOT -ErrorAction SilentlyContinue

$python = (Resolve-Path (Join-Path $projectRoot '.venv\Scripts\python.exe')).Path
$pythonw = (Resolve-Path (Join-Path $projectRoot '.venv\Scripts\pythonw.exe')).Path

if ($ValidateOnly) {
    & $python -c "import arkclaw.presentation.qt.pet_application as m; print(m.__file__)"
    exit $LASTEXITCODE
}

$launcher = if ($Console) { $python } else { $pythonw }
& $launcher -c "from arkclaw.presentation.qt.pet_application import run; run()"

