[CmdletBinding()]
param(
    [string]$AssetRoot = 'D:\Spine\test\stage3_idle_rebuild_20260806_145235\runtime_input',
    [switch]$Console,
    [switch]$ValidateOnly,
    [switch]$Smoke
)

$ErrorActionPreference = 'Stop'

$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
Set-Location $projectRoot

function Resolve-ArkClawPythonExecutable {
    param(
        [Parameter(Mandatory = $true)]
        [ValidateSet('python.exe', 'pythonw.exe')]
        [string]$ExecutableName
    )

    $candidateRoots = [System.Collections.Generic.List[string]]::new()
    $candidateRoots.Add((Join-Path $projectRoot '.venv'))

    $projectParent = Split-Path -Parent $projectRoot
    if ((Split-Path -Leaf $projectParent) -eq '.worktrees') {
        $repositoryRoot = Split-Path -Parent $projectParent
        $sharedRoot = Join-Path $repositoryRoot '.venv'
        if ($sharedRoot -ne $candidateRoots[0]) {
            $candidateRoots.Add($sharedRoot)
        }
    }

    $checked = [System.Collections.Generic.List[string]]::new()
    foreach ($candidateRoot in $candidateRoots) {
        $candidate = Join-Path $candidateRoot (Join-Path 'Scripts' $ExecutableName)
        $checked.Add($candidate)
        if (Test-Path -LiteralPath $candidate -PathType Leaf) {
            return (Resolve-Path -LiteralPath $candidate).Path
        }
    }

    throw (
        'arkclaw_python_runtime_missing: checked ' +
        ($checked -join '; ')
    )
}

$sourceRoot = (Resolve-Path (Join-Path $projectRoot 'src')).Path
$bridgeDll = (Resolve-Path (Join-Path $projectRoot 'build\spine38\Release\arkclaw_spine38_bridge.dll')).Path
$resolvedAssetRoot = (Resolve-Path -LiteralPath $AssetRoot).Path
$skeleton = (Resolve-Path -LiteralPath (Join-Path $resolvedAssetRoot 'build_char_340_shwaz_striker#1.skel')).Path
$atlas = (Resolve-Path -LiteralPath (Join-Path $resolvedAssetRoot 'build_char_340_shwaz_striker#1.atlas')).Path
$texture = (Resolve-Path -LiteralPath (Join-Path $resolvedAssetRoot 'build_char_340_shwaz_striker#1.png')).Path
$manifestPath = Join-Path $projectRoot 'build\schwarz-production.local.json'
$python = Resolve-ArkClawPythonExecutable -ExecutableName 'python.exe'
$pythonw = Resolve-ArkClawPythonExecutable -ExecutableName 'pythonw.exe'

$manifest = [ordered]@{
    schema_version = 1
    pack_id = 'schwarz-production'
    spine_version = '3.8'
    assets = [ordered]@{
        skeleton = $skeleton
        atlas = $atlas
        texture = $texture
    }
    expected_sha256 = [ordered]@{
        skeleton = (Get-FileHash -LiteralPath $skeleton -Algorithm SHA256).Hash.ToLowerInvariant()
        atlas = (Get-FileHash -LiteralPath $atlas -Algorithm SHA256).Hash.ToLowerInvariant()
        texture = (Get-FileHash -LiteralPath $texture -Algorithm SHA256).Hash.ToLowerInvariant()
    }
    animations = [ordered]@{
        relax = 'Relax'
        move = 'Move'
        sit = 'Sit'
        sleep = 'Sleep'
        special = 'Special'
        interact = 'Interact'
    }
    direction_policy = 'mirror_move'
    framing = [ordered]@{
        scale = 1.0
        x_offset = 0.0
        foot_baseline = 180.0
    }
    texture_page_count = 1
}

$manifestJson = $manifest | ConvertTo-Json -Depth 4
[System.IO.File]::WriteAllText(
    $manifestPath,
    $manifestJson,
    [System.Text.UTF8Encoding]::new($false)
)

# The worktree and the main repository currently share a virtual environment.
# PYTHONPATH makes the selected worktree authoritative instead of the editable
# path recorded inside that shared environment.
$env:PYTHONPATH = $sourceRoot
$env:ARKCLAW_SPINE38_BRIDGE_DLL = $bridgeDll
$env:ARKCLAW_PET_ROLE_MANIFEST = $manifestPath
$env:ARKCLAW_SPINE38_ASSET_ROOT = $resolvedAssetRoot

if ($ValidateOnly) {
    & $python -c "import arkclaw.presentation.qt.pet_application as m; print(m.__file__)"
    if ($LASTEXITCODE -ne 0) {
        exit $LASTEXITCODE
    }
    Write-Output "Python runtime: $python"
    Write-Output "Role manifest: $manifestPath"
    Write-Output "Spine bridge: $bridgeDll"
    Write-Output "Asset root: $resolvedAssetRoot"
    exit 0
}

if ($Smoke) {
    & $python -m pytest `
        -p no:cacheprovider `
        'tests\integration\test_spine38_schwarz_catalog.py' `
        'tests\qt\test_spine38_schwarz_smoke.py' `
        -v
    exit $LASTEXITCODE
}

$launcher = if ($Console) { $python } else { $pythonw }
& $launcher -c "from arkclaw.presentation.qt.pet_application import run; run()"
