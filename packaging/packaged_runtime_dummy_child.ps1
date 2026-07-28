param(
    [Parameter(Mandatory = $true)]
    [string]$ControlRoot
)

$ErrorActionPreference = "Stop"
$RepositoryRoot = "D:\SJTUClaw"
$AllowedParent = Join-Path `
    $RepositoryRoot `
    "build\packaged-runtime-supervisor-recovery"
$ResolvedControlRoot = [IO.Path]::GetFullPath($ControlRoot)
$ResolvedParent = Split-Path -Parent $ResolvedControlRoot
$AllowedAttempts = @(
    "attempt-01",
    "attempt-02",
    "attempt-03",
    "attempt-04",
    "attempt-05",
    "attempt-06"
)
if (
    -not [string]::Equals(
        $ResolvedParent,
        $AllowedParent,
        [StringComparison]::OrdinalIgnoreCase
    ) -or
    (Split-Path -Leaf $ResolvedControlRoot) -notin $AllowedAttempts
) {
    exit 2
}

$PidPath = Join-Path $ResolvedControlRoot "dummy-pid.json"
$StopPath = Join-Path $ResolvedControlRoot "stop.signal"
$TemporaryPidPath = Join-Path `
    $ResolvedControlRoot `
    (".dummy-pid-{0}.part" -f [Guid]::NewGuid().ToString("N"))
$PidDocument = [ordered]@{
    schema_version = 1
    dummy_pid = $PID
    network_created = $false
    environment_values_read = $false
}
$Payload = ($PidDocument | ConvertTo-Json -Compress) + [Environment]::NewLine
$Encoding = [Text.UTF8Encoding]::new($false)
$Stream = [IO.FileStream]::new(
    $TemporaryPidPath,
    [IO.FileMode]::CreateNew,
    [IO.FileAccess]::Write,
    [IO.FileShare]::None
)
try {
    $Writer = [IO.StreamWriter]::new($Stream, $Encoding)
    try {
        $Writer.Write($Payload)
        $Writer.Flush()
        $Stream.Flush($true)
    } finally {
        $Writer.Dispose()
    }
} finally {
    $Stream.Dispose()
}
[IO.File]::Move($TemporaryPidPath, $PidPath)

$Deadline = [DateTime]::UtcNow.AddSeconds(30)
while ([DateTime]::UtcNow -lt $Deadline) {
    if (Test-Path -LiteralPath $StopPath -PathType Leaf) {
        exit 0
    }
    [Threading.Thread]::Sleep(20)
}
exit 3
