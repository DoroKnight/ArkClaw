param(
    [ValidateSet("Disabled", "EnvironmentTest", "Dummy", "Diagnostic")]
    [string]$Mode = "Disabled",

    [switch]$ConfirmDiagnostic,

    [ValidateSet(
        "attempt-01",
        "attempt-02",
        "attempt-03",
        "attempt-04",
        "attempt-05",
        "attempt-06"
    )]
    [string]$AttemptName = "attempt-01",

    [ValidateSet(
        "None",
        "SamplerFirst",
        "SamplerMid",
        "RawWrite",
        "SummaryWrite",
        "Serialization",
        "Refresh",
        "Wait",
        "Finalize",
        "Cancel"
    )]
    [string]$TestFault = "None"
)

if ($Mode -ceq "Disabled") {
    Write-Output (
        "packaged_runtime_supervisor=False " +
        "safe_code=packaged_runtime_supervisor_disabled"
    )
    exit 0
}

$ErrorActionPreference = "Stop"

$RepositoryRoot = "D:\SJTUClaw"
$RecoveryRoot = Join-Path `
    $RepositoryRoot `
    "build\packaged-runtime-supervisor-recovery"
$VerificationRoot = if ($Mode -ceq "Dummy") {
    Join-Path $RecoveryRoot $AttemptName
} elseif ($Mode -ceq "EnvironmentTest") {
    Join-Path $RecoveryRoot "environment-test"
} else {
    Join-Path $RecoveryRoot "packaged-diagnostic"
}
$DistRoot = Join-Path $RepositoryRoot "dist\SJTUClaw.dist"
$ExecutablePath = Join-Path $DistRoot "SJTUClaw.exe"
$DummyPowerShellPath = "$PSHOME\powershell.exe"
$DummyScriptPath = Join-Path `
    $RepositoryRoot `
    "packaging\packaged_runtime_dummy_child.ps1"
$EnvironmentResultPath = Join-Path $VerificationRoot "environment-test.json"
$RawObservationPath = Join-Path $VerificationRoot "tcp-observations.jsonl"
$SummaryPath = Join-Path $VerificationRoot "diagnostic-summary.json"
$CheckpointPath = Join-Path $VerificationRoot "supervisor-checkpoint.json"
$StopSignalPath = Join-Path $VerificationRoot "stop.signal"
$ExpectedEnvironmentAssertionCount = 9
$SensitiveNameFragments = @(
    "API_KEY",
    "APIKEY",
    "AUTHORIZATION",
    "BEARER",
    "CREDENTIAL",
    "PASSWORD",
    "SECRET",
    "TOKEN",
    "COOKIE"
)
$ProxyNames = @(
    "HTTP_PROXY",
    "HTTPS_PROXY",
    "ALL_PROXY",
    "NO_PROXY"
)
$RedirectedPaths = [ordered]@{
    TEMP = Join-Path $VerificationRoot "temp"
    TMP = Join-Path $VerificationRoot "tmp"
    TMPDIR = Join-Path $VerificationRoot "tmpdir"
    LOCALAPPDATA = Join-Path $VerificationRoot "localappdata"
    APPDATA = Join-Path $VerificationRoot "appdata"
    HOME = Join-Path $VerificationRoot "home"
    USERPROFILE = Join-Path $VerificationRoot "userprofile"
}
$SupervisorPhase = "created"
$PhaseSequence = 0
$ChildPid = $null
$ChildCreated = $false
$ChildRunning = $false
$ChildExitObserved = $false
$PollAttemptCount = 0
$SuccessfulPollCount = 0
$LastSuccessfulPollUtc = $null
$RawObservationCount = 0
$TerminalSummaryWritten = $false
$SupervisorSafeCode = "supervisor_in_progress"
$SupervisorOutputLine = ""

function Get-SafeExceptionCategory {
    param([Parameter(Mandatory = $true)][Exception]$Exception)

    $candidate = $Exception
    while (
        $null -ne $candidate.InnerException -and
        (
            $candidate -is [Management.Automation.RuntimeException] -or
            $candidate -is [Management.Automation.MethodInvocationException]
        )
    ) {
        $candidate = $candidate.InnerException
    }
    if ($candidate -is [OperationCanceledException]) {
        return "cancelled"
    }
    if ($candidate -is [UnauthorizedAccessException]) {
        return "unauthorized_access"
    }
    if ($candidate -is [IO.IOException]) {
        return "io"
    }
    if ($candidate -is [ArgumentException]) {
        return "argument"
    }
    if ($candidate -is [InvalidOperationException]) {
        return "invalid_operation"
    }
    return "unknown_safe_category"
}

function Get-SafeCheckpoint {
    return [ordered]@{
        schema_version = 1
        supervisor_phase = $script:SupervisorPhase
        phase_sequence = $script:PhaseSequence
        child_pid = $script:ChildPid
        child_created = $script:ChildCreated
        child_running = $script:ChildRunning
        child_exit_observed = $script:ChildExitObserved
        poll_attempt_count = $script:PollAttemptCount
        successful_poll_count = $script:SuccessfulPollCount
        last_successful_poll_utc = $script:LastSuccessfulPollUtc
        raw_observation_count = $script:RawObservationCount
        terminal_summary_written = $script:TerminalSummaryWritten
        safe_code = $script:SupervisorSafeCode
    }
}

function Set-SupervisorPhase {
    param(
        [Parameter(Mandatory = $true)]
        [ValidateSet(
            "created",
            "preconditions_validated",
            "child_created",
            "child_running",
            "observing",
            "child_exit_observed",
            "finalizing",
            "completed",
            "supervisor_failed"
        )]
        [string]$Phase
    )

    $script:SupervisorPhase = $Phase
    $script:PhaseSequence += 1
    Write-SafeJsonAtomically `
        -Path $CheckpointPath `
        -Document (Get-SafeCheckpoint)
}

function Write-RawObservationLine {
    param([Parameter(Mandatory = $true)][object]$Document)

    if ($TestFault -ceq "Serialization") {
        throw [InvalidOperationException]::new(
            "fault_serialization"
        )
    }
    $payload = ($Document | ConvertTo-Json -Compress -Depth 5)
    if ($TestFault -ceq "RawWrite") {
        throw [IO.IOException]::new("fault_raw_write")
    }
    $encoding = [Text.UTF8Encoding]::new($false)
    $stream = [IO.FileStream]::new(
        $RawObservationPath,
        [IO.FileMode]::Append,
        [IO.FileAccess]::Write,
        [IO.FileShare]::Read
    )
    try {
        $writer = [IO.StreamWriter]::new($stream, $encoding)
        try {
            $writer.WriteLine($payload)
            $writer.Flush()
            $stream.Flush($true)
        } finally {
            $writer.Dispose()
        }
    } finally {
        $stream.Dispose()
    }
    $script:RawObservationCount += 1
}

function Write-SafeJsonAtomically {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Path,

        [Parameter(Mandatory = $true)]
        [object]$Document
    )

    $directory = Split-Path -Parent $Path
    New-Item -ItemType Directory -Path $directory -Force | Out-Null
    $temporaryPath = Join-Path `
        $directory `
        (".evidence-{0}.part" -f [Guid]::NewGuid().ToString("N"))
    $backupPath = Join-Path `
        $directory `
        (".evidence-{0}.backup" -f [Guid]::NewGuid().ToString("N"))
    $payload = ($Document | ConvertTo-Json -Depth 8) + [Environment]::NewLine
    $encoding = [Text.UTF8Encoding]::new($false)
    $stream = [IO.FileStream]::new(
        $temporaryPath,
        [IO.FileMode]::CreateNew,
        [IO.FileAccess]::Write,
        [IO.FileShare]::None
    )
    try {
        $writer = [IO.StreamWriter]::new($stream, $encoding)
        try {
            $writer.Write($payload)
            $writer.Flush()
            $stream.Flush($true)
        } finally {
            $writer.Dispose()
        }
    } finally {
        $stream.Dispose()
    }
    if (Test-Path -LiteralPath $Path) {
        try {
            [IO.File]::Replace($temporaryPath, $Path, $backupPath)
        } finally {
            if (Test-Path -LiteralPath $backupPath -PathType Leaf) {
                try {
                    [IO.File]::Delete($backupPath)
                } catch {
                }
            }
        }
    } else {
        [IO.File]::Move($temporaryPath, $Path)
    }
}

function Test-SensitiveEnvironmentName {
    param([Parameter(Mandatory = $true)][string]$Name)

    $upperName = $Name.ToUpperInvariant()
    foreach ($fragment in $SensitiveNameFragments) {
        if ($upperName.Contains($fragment)) {
            return $true
        }
    }
    return $false
}

function Test-ProxyEnvironmentName {
    param([Parameter(Mandatory = $true)][string]$Name)

    foreach ($proxyName in $ProxyNames) {
        if ([string]::Equals(
            $Name,
            $proxyName,
            [StringComparison]::OrdinalIgnoreCase
        )) {
            return $true
        }
    }
    return $false
}

function Get-RawProcessEnvironmentEntries {
    return @(
        [Environment]::GetEnvironmentVariables(
            [EnvironmentVariableTarget]::Process
        ).GetEnumerator() |
            ForEach-Object {
                [pscustomobject]@{
                    Name = [string]$_.Key
                    Value = [string]$_.Value
                }
            }
    )
}

function Initialize-RedirectedDirectories {
    $requiredPrefix = $VerificationRoot + [IO.Path]::DirectorySeparatorChar
    foreach ($path in $RedirectedPaths.Values) {
        $absolutePath = [IO.Path]::GetFullPath($path)
        if (-not $absolutePath.StartsWith(
            $requiredPrefix,
            [StringComparison]::OrdinalIgnoreCase
        )) {
            throw [InvalidOperationException]::new(
                "redirected_path_invalid"
            )
        }
        New-Item -ItemType Directory -Path $absolutePath -Force | Out-Null
        $item = Get-Item -LiteralPath $absolutePath -Force
        if (
            ($item.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0
        ) {
            throw [InvalidOperationException]::new(
                "redirected_path_reparse_point"
            )
        }
    }
}

function New-NormalizedEnvironment {
    param(
        [Parameter(Mandatory = $true)]
        [object[]]$Entries,

        [Parameter(Mandatory = $true)]
        [string]$CanonicalPath
    )

    if ([string]::IsNullOrWhiteSpace($CanonicalPath)) {
        throw [InvalidOperationException]::new("path_unavailable")
    }
    $environment = [Collections.Generic.Dictionary[string,string]]::new(
        [StringComparer]::OrdinalIgnoreCase
    )
    foreach ($entry in $Entries) {
        $name = [string]$entry.Name
        $value = [string]$entry.Value
        if ([string]::Equals(
            $name,
            "Path",
            [StringComparison]::OrdinalIgnoreCase
        )) {
            continue
        }
        if (
            (Test-SensitiveEnvironmentName -Name $name) -or
            (Test-ProxyEnvironmentName -Name $name)
        ) {
            continue
        }
        if ($environment.ContainsKey($name)) {
            if (-not [string]::Equals(
                $environment[$name],
                $value,
                [StringComparison]::Ordinal
            )) {
                throw [InvalidOperationException]::new(
                    "environment_conflict"
                )
            }
            continue
        }
        $environment[$name] = $value
    }
    $environment["Path"] = $CanonicalPath
    foreach ($entry in $RedirectedPaths.GetEnumerator()) {
        $environment[$entry.Key] = [IO.Path]::GetFullPath($entry.Value)
    }
    return $environment
}

function Set-SupervisorProcessEnvironment {
    param(
        [Parameter(Mandatory = $true)]
        [object[]]$OriginalEntries,

        [Parameter(Mandatory = $true)]
        [Collections.Generic.Dictionary[string,string]]$NormalizedEnvironment
    )

    try {
        foreach ($entry in $OriginalEntries) {
            [Environment]::SetEnvironmentVariable(
                [string]$entry.Name,
                $null,
                [EnvironmentVariableTarget]::Process
            )
        }
        foreach ($entry in $NormalizedEnvironment.GetEnumerator()) {
            [Environment]::SetEnvironmentVariable(
                $entry.Key,
                $entry.Value,
                [EnvironmentVariableTarget]::Process
            )
        }
    } catch {
        throw [InvalidOperationException]::new(
            "process_environment_normalization_failed"
        )
    }
}

function Get-EnvironmentAssertions {
    param([Parameter(Mandatory = $true)][object[]]$Entries)

    $values = [Collections.Generic.Dictionary[string,string]]::new(
        [StringComparer]::OrdinalIgnoreCase
    )
    $duplicateCount = 0
    $pathVariantCount = 0
    $sensitiveCount = 0
    $proxyCount = 0
    foreach ($entry in $Entries) {
        $name = [string]$entry.Name
        $value = [string]$entry.Value
        if ($values.ContainsKey($name)) {
            $duplicateCount += 1
            continue
        }
        $values.Add($name, $value)
        if ([string]::Equals(
            $name,
            "Path",
            [StringComparison]::OrdinalIgnoreCase
        )) {
            $pathVariantCount += 1
        }
        if (Test-SensitiveEnvironmentName -Name $name) {
            $sensitiveCount += 1
        }
        if (Test-ProxyEnvironmentName -Name $name) {
            $proxyCount += 1
        }
    }
    $outsideCount = 0
    $requiredCount = 0
    $requiredPrefix = $VerificationRoot + [IO.Path]::DirectorySeparatorChar
    foreach ($name in $RedirectedPaths.Keys) {
        if (-not $values.ContainsKey($name)) {
            $outsideCount += 1
            continue
        }
        $value = [IO.Path]::GetFullPath($values[$name])
        $expectedValue = [IO.Path]::GetFullPath($RedirectedPaths[$name])
        if (-not $value.StartsWith(
            $requiredPrefix,
            [StringComparison]::OrdinalIgnoreCase
        )) {
            $outsideCount += 1
        }
        if ([string]::Equals(
            $value,
            $expectedValue,
            [StringComparison]::OrdinalIgnoreCase
        )) {
            $requiredCount += 1
        }
    }
    return [pscustomobject]@{
        case_insensitive_duplicate_count = $duplicateCount
        path_variant_count = $pathVariantCount
        sensitive_environment_name_count = $sensitiveCount
        proxy_environment_name_count = $proxyCount
        redirected_path_outside_repository_count = $outsideCount
        required_redirected_path_count = $requiredCount
    }
}

function Initialize-SafeProcessEnvironment {
    Initialize-RedirectedDirectories
    $originalEntries = @(Get-RawProcessEnvironmentEntries)
    $canonicalPath = [Environment]::GetEnvironmentVariable(
        "Path",
        [EnvironmentVariableTarget]::Process
    )
    $normalized = New-NormalizedEnvironment `
        -Entries $originalEntries `
        -CanonicalPath $canonicalPath
    Set-SupervisorProcessEnvironment `
        -OriginalEntries $originalEntries `
        -NormalizedEnvironment $normalized
    $actualEntries = @(Get-RawProcessEnvironmentEntries)
    $assertions = Get-EnvironmentAssertions -Entries $actualEntries
    if (
        $assertions.case_insensitive_duplicate_count -ne 0 -or
        $assertions.path_variant_count -ne 1 -or
        $assertions.sensitive_environment_name_count -ne 0 -or
        $assertions.proxy_environment_name_count -ne 0 -or
        $assertions.redirected_path_outside_repository_count -ne 0 -or
        $assertions.required_redirected_path_count -ne 7
    ) {
        throw [InvalidOperationException]::new(
            "process_environment_assertion_failed"
        )
    }
    return $assertions
}

function Test-StrictLoopbackAddress {
    param([Parameter(Mandatory = $true)][string]$Address)

    $parsed = $null
    if (-not [Net.IPAddress]::TryParse($Address, [ref]$parsed)) {
        return $false
    }
    if ($parsed.AddressFamily -eq [Net.Sockets.AddressFamily]::InterNetwork) {
        return $parsed.GetAddressBytes()[0] -eq 127
    }
    if ($parsed.Equals([Net.IPAddress]::IPv6Loopback)) {
        return $true
    }
    if ($parsed.IsIPv4MappedToIPv6) {
        return $parsed.MapToIPv4().GetAddressBytes()[0] -eq 127
    }
    return $false
}

function Test-UnspecifiedAddress {
    param([Parameter(Mandatory = $true)][string]$Address)

    $parsed = $null
    if (-not [Net.IPAddress]::TryParse($Address, [ref]$parsed)) {
        return $false
    }
    return (
        $parsed.Equals([Net.IPAddress]::Any) -or
        $parsed.Equals([Net.IPAddress]::IPv6Any)
    )
}

function Get-AddressCategory {
    param([Parameter(Mandatory = $true)][string]$Address)

    $parsed = $null
    if (-not [Net.IPAddress]::TryParse($Address, [ref]$parsed)) {
        return "invalid"
    }
    if (Test-StrictLoopbackAddress -Address $Address) {
        return "loopback"
    }
    if (Test-UnspecifiedAddress -Address $Address) {
        return "unspecified"
    }
    if ($parsed.IsIPv6LinkLocal) {
        return "link_local"
    }
    if (
        $parsed.AddressFamily -eq
            [Net.Sockets.AddressFamily]::InterNetwork
    ) {
        $bytes = $parsed.GetAddressBytes()
        if (
            $bytes[0] -eq 10 -or
            ($bytes[0] -eq 172 -and $bytes[1] -ge 16 -and $bytes[1] -le 31) -or
            ($bytes[0] -eq 192 -and $bytes[1] -eq 168)
        ) {
            return "private"
        }
        if ($bytes[0] -eq 169 -and $bytes[1] -eq 254) {
            return "link_local"
        }
    }
    return "external"
}

function Get-Sha256Text {
    param([Parameter(Mandatory = $true)][string]$Value)

    $bytes = [Text.Encoding]::UTF8.GetBytes($Value)
    $sha256 = [Security.Cryptography.SHA256]::Create()
    try {
        $hex = [BitConverter]::ToString($sha256.ComputeHash($bytes))
        return $hex.Replace("-", "").ToLowerInvariant()
    } finally {
        $sha256.Dispose()
    }
}

function Get-SafeEndpointEvidence {
    param(
        [Parameter(Mandatory = $true)]
        [object]$Endpoint,

        [Parameter(Mandatory = $true)]
        [int]$PollIndex,

        [Parameter(Mandatory = $true)]
        [string]$Timestamp
    )

    $forward = (
        "{0}|{1}|{2}|{3}|{4}|{5}" -f
        $Endpoint.owning_process,
        $Endpoint.state,
        $Endpoint.local_address,
        $Endpoint.local_port,
        $Endpoint.remote_address,
        $Endpoint.remote_port
    )
    $firstSide = (
        "{0}|{1}" -f
        $Endpoint.local_address,
        $Endpoint.local_port
    )
    $secondSide = (
        "{0}|{1}" -f
        $Endpoint.remote_address,
        $Endpoint.remote_port
    )
    $flowMaterial = if (
        [string]::CompareOrdinal($firstSide, $secondSide) -le 0
    ) {
        "$firstSide|$secondSide"
    } else {
        "$secondSide|$firstSide"
    }
    return [ordered]@{
        schema_version = 1
        poll_index = $PollIndex
        timestamp_utc = $Timestamp
        child_pid = $script:ChildPid
        sampler_success = $true
        sampler_safe_code = "none"
        endpoint_key = Get-Sha256Text -Value $forward
        flow_key = Get-Sha256Text -Value $flowMaterial
        state = $Endpoint.state
        local_address_category = Get-AddressCategory `
            -Address $Endpoint.local_address
        remote_address_category = Get-AddressCategory `
            -Address $Endpoint.remote_address
        local_port = $Endpoint.local_port
        remote_port = $Endpoint.remote_port
    }
}

function Get-TcpRowsForProcess {
    param([Parameter(Mandatory = $true)][int]$ProcessId)

    return @(
        Get-NetTCPConnection `
            -OwningProcess $ProcessId `
            -ErrorAction SilentlyContinue |
            ForEach-Object {
                [pscustomobject]@{
                    owning_process = [int]$_.OwningProcess
                    state = [string]$_.State
                    local_address = [string]$_.LocalAddress
                    local_port = [int]$_.LocalPort
                    remote_address = [string]$_.RemoteAddress
                    remote_port = [int]$_.RemotePort
                }
            }
    )
}

function Get-EndpointKey {
    param([Parameter(Mandatory = $true)][object]$Endpoint)

    return (
        "{0}|{1}|{2}|{3}|{4}|{5}" -f
        $Endpoint.owning_process,
        $Endpoint.state.ToLowerInvariant(),
        $Endpoint.local_address.ToLowerInvariant(),
        $Endpoint.local_port,
        $Endpoint.remote_address.ToLowerInvariant(),
        $Endpoint.remote_port
    )
}

function Add-TcpObservationPoll {
    param(
        [Parameter(Mandatory = $true)]
        [Collections.Generic.Dictionary[string,object]]$Observations,

        [Parameter(Mandatory = $true)]
        [object[]]$Endpoints,

        [Parameter(Mandatory = $true)]
        [int]$PollNumber
    )

    $seen = [Collections.Generic.HashSet[string]]::new(
        [StringComparer]::Ordinal
    )
    $sampleCount = 0
    foreach ($endpoint in $Endpoints) {
        if (
            $endpoint.state -cne "Bound" -and
            $endpoint.state -cne "Listen" -and
            $endpoint.state -cne "Established"
        ) {
            continue
        }
        $key = Get-EndpointKey -Endpoint $endpoint
        if (-not $seen.Add($key)) {
            continue
        }
        $sampleCount += 1
        if ($Observations.ContainsKey($key)) {
            $record = $Observations[$key]
            $record.last_poll = $PollNumber
            $record.sample_count += 1
        } else {
            $Observations[$key] = [pscustomobject]@{
                owning_process = $endpoint.owning_process
                state = $endpoint.state
                local_address = $endpoint.local_address
                local_port = $endpoint.local_port
                remote_address = $endpoint.remote_address
                remote_port = $endpoint.remote_port
                first_poll = $PollNumber
                last_poll = $PollNumber
                sample_count = 1
            }
        }
    }
    return $sampleCount
}

function Get-DiagnosticSummary {
    param(
        [Parameter(Mandatory = $true)]
        [Collections.Generic.Dictionary[string,object]]$Observations,

        [Parameter(Mandatory = $true)]
        [int]$PollCount,

        [Parameter(Mandatory = $true)]
        [int]$SampleCount,

        [Parameter(Mandatory = $true)]
        [bool]$ProcessExitObserved,

        [Parameter(Mandatory = $true)]
        [bool]$EndpointsDisappearedAfterExit,

        [Parameter(Mandatory = $true)]
        [bool]$PidReuseDetected,

        [Parameter(Mandatory = $true)]
        [bool]$GuiWindowObserved,

        [Parameter(Mandatory = $true)]
        [int]$ExitCode
    )

    $endpoints = @($Observations.Values)
    $bound = @($endpoints | Where-Object { $_.state -ceq "Bound" })
    $listen = @($endpoints | Where-Object { $_.state -ceq "Listen" })
    $established = @(
        $endpoints | Where-Object { $_.state -ceq "Established" }
    )
    $strictLoopbackEstablished = @()
    $externalCount = 0
    foreach ($endpoint in $established) {
        if (
            (Test-StrictLoopbackAddress -Address $endpoint.local_address) -and
            (Test-StrictLoopbackAddress -Address $endpoint.remote_address)
        ) {
            $strictLoopbackEstablished += $endpoint
        } else {
            $externalCount += 1
        }
    }
    foreach ($endpoint in $listen) {
        if (-not (Test-StrictLoopbackAddress -Address $endpoint.local_address)) {
            $externalCount += 1
        }
    }

    $reversePair = $false
    if ($strictLoopbackEstablished.Count -eq 2) {
        $first = $strictLoopbackEstablished[0]
        $second = $strictLoopbackEstablished[1]
        $reversePair = (
            $first.local_address -ceq $second.remote_address -and
            $first.local_port -eq $second.remote_port -and
            $first.remote_address -ceq $second.local_address -and
            $first.remote_port -eq $second.local_port
        )
    }
    $boundMatchesPair = $false
    if ($reversePair -and $bound.Count -eq 1) {
        $boundAddressAllowed = (
            (Test-StrictLoopbackAddress -Address $bound[0].local_address) -or
            (Test-UnspecifiedAddress -Address $bound[0].local_address)
        )
        $boundMatchesPair = (
            $boundAddressAllowed -and
            (
                $bound[0].local_port -eq
                    $strictLoopbackEstablished[0].local_port -or
                $bound[0].local_port -eq
                    $strictLoopbackEstablished[0].remote_port
            )
        )
    }
    $verified = (
        $ProcessExitObserved -and
        $EndpointsDisappearedAfterExit -and
        -not $PidReuseDetected -and
        $ExitCode -eq 0 -and
        $endpoints.Count -eq 3 -and
        $bound.Count -eq 1 -and
        $listen.Count -eq 0 -and
        $established.Count -eq 2 -and
        $externalCount -eq 0 -and
        $reversePair -and
        $boundMatchesPair
    )
    $loopbackCount = if ($verified) {
        3
    } else {
        $strictLoopbackEstablished.Count
    }
    $unattributedCount = if ($verified) {
        0
    } else {
        $endpoints.Count - $externalCount - $loopbackCount
    }
    $safeCode = if ($externalCount -gt 0) {
        "packaged_runtime_external_network_detected"
    } elseif ($PidReuseDetected) {
        "packaged_runtime_pid_identity_changed"
    } elseif (
        -not $ProcessExitObserved -or
        -not $EndpointsDisappearedAfterExit
    ) {
        "packaged_runtime_network_cleanup_failed"
    } elseif ($verified) {
        "corrective_packaged_runtime_diagnostic_verified"
    } else {
        "packaged_runtime_network_signature_unattributed"
    }
    return [ordered]@{
        schema_version = 1
        observer_authority = "Get-NetTCPConnection"
        poll_count = $PollCount
        sample_count = $SampleCount
        unique_endpoint_count = $endpoints.Count
        bound_endpoint_count = $bound.Count
        listen_endpoint_count = $listen.Count
        established_endpoint_count = $established.Count
        loopback_endpoint_count = $loopbackCount
        external_endpoint_count = $externalCount
        unattributed_endpoint_count = $unattributedCount
        unique_flow_count = $(if ($reversePair) { 1 } else { 0 })
        process_exit_observed = $ProcessExitObserved
        endpoints_disappeared_after_exit = $EndpointsDisappearedAfterExit
        pid_reuse_detected = $PidReuseDetected
        gui_window_observed = $GuiWindowObserved
        external_process_created = $false
        executable_creation_count = 1
        packaged_local_channel_verified = $verified
        environment_values_recorded = $false
        exit_code = $ExitCode
        safe_code = $safeCode
    }
}

function Get-DiagnosticSummaryFromDisk {
    param(
        [Parameter(Mandatory = $true)]
        [bool]$ProcessExitObserved,

        [Parameter(Mandatory = $true)]
        [bool]$EndpointsDisappearedAfterExit,

        [Parameter(Mandatory = $true)]
        [bool]$PidReuseDetected,

        [Parameter(Mandatory = $true)]
        [bool]$GuiWindowObserved,

        [Parameter(Mandatory = $true)]
        [int]$ExitCode
    )

    $records = @()
    if (Test-Path -LiteralPath $RawObservationPath -PathType Leaf) {
        foreach ($line in [IO.File]::ReadLines($RawObservationPath)) {
            if (-not [string]::IsNullOrWhiteSpace($line)) {
                $records += $line | ConvertFrom-Json
            }
        }
    }
    $successfulRecords = @(
        $records | Where-Object { $_.sampler_success -eq $true }
    )
    $endpointRecords = @(
        $successfulRecords |
            Where-Object { $null -ne $_.endpoint_key } |
            Group-Object -Property endpoint_key |
            ForEach-Object { $_.Group[0] }
    )
    $bound = @($endpointRecords | Where-Object { $_.state -ceq "Bound" })
    $listen = @($endpointRecords | Where-Object { $_.state -ceq "Listen" })
    $established = @(
        $endpointRecords | Where-Object { $_.state -ceq "Established" }
    )
    $loopbackEstablished = @(
        $established |
            Where-Object {
                $_.local_address_category -ceq "loopback" -and
                $_.remote_address_category -ceq "loopback"
            }
    )
    $externalCount = @(
        $established |
            Where-Object {
                $_.local_address_category -cne "loopback" -or
                $_.remote_address_category -cne "loopback"
            }
    ).Count
    $externalCount += @(
        $listen |
            Where-Object {
                $_.local_address_category -cne "loopback"
            }
    ).Count
    $reversePair = (
        $loopbackEstablished.Count -eq 2 -and
        $loopbackEstablished[0].flow_key -ceq
            $loopbackEstablished[1].flow_key -and
        $loopbackEstablished[0].local_port -eq
            $loopbackEstablished[1].remote_port -and
        $loopbackEstablished[0].remote_port -eq
            $loopbackEstablished[1].local_port
    )
    $boundMatchesPair = (
        $reversePair -and
        $bound.Count -eq 1 -and
        (
            $bound[0].local_address_category -ceq "loopback" -or
            $bound[0].local_address_category -ceq "unspecified"
        ) -and
        (
            $bound[0].local_port -eq
                $loopbackEstablished[0].local_port -or
            $bound[0].local_port -eq
                $loopbackEstablished[0].remote_port
        )
    )
    $verified = (
        $ProcessExitObserved -and
        $EndpointsDisappearedAfterExit -and
        -not $PidReuseDetected -and
        $ExitCode -eq 0 -and
        $endpointRecords.Count -eq 3 -and
        $bound.Count -eq 1 -and
        $listen.Count -eq 0 -and
        $established.Count -eq 2 -and
        $externalCount -eq 0 -and
        $reversePair -and
        $boundMatchesPair
    )
    $loopbackCount = if ($verified) {
        3
    } else {
        $loopbackEstablished.Count
    }
    $unattributedCount = if ($verified) {
        0
    } else {
        $endpointRecords.Count - $externalCount - $loopbackCount
    }
    $safeCode = if ($Mode -ceq "Dummy" -and $ExitCode -eq 0) {
        "dummy_supervisor_lifecycle_verified"
    } elseif ($externalCount -gt 0) {
        "packaged_runtime_external_network_detected"
    } elseif ($PidReuseDetected) {
        "packaged_runtime_pid_identity_changed"
    } elseif (
        -not $ProcessExitObserved -or
        -not $EndpointsDisappearedAfterExit
    ) {
        "packaged_runtime_network_cleanup_failed"
    } elseif ($verified) {
        "corrective_packaged_runtime_diagnostic_verified"
    } else {
        "packaged_runtime_network_signature_unattributed"
    }
    $pollCount = if ($records.Count -eq 0) {
        0
    } else {
        [int](($records | Measure-Object -Property poll_index -Maximum).Maximum)
    }
    return [ordered]@{
        schema_version = 2
        observer_authority = "Get-NetTCPConnection"
        mode = $Mode
        poll_attempt_count = $script:PollAttemptCount
        successful_poll_count = $script:SuccessfulPollCount
        poll_count = $pollCount
        raw_observation_count = $records.Count
        unique_endpoint_count = $endpointRecords.Count
        bound_endpoint_count = $bound.Count
        listen_endpoint_count = $listen.Count
        established_endpoint_count = $established.Count
        loopback_endpoint_count = $loopbackCount
        external_endpoint_count = $externalCount
        unattributed_endpoint_count = $unattributedCount
        unique_flow_count = $(if ($reversePair) { 1 } else { 0 })
        process_exit_observed = $ProcessExitObserved
        endpoints_disappeared_after_exit = $EndpointsDisappearedAfterExit
        pid_reuse_detected = $PidReuseDetected
        gui_window_observed = $GuiWindowObserved
        child_created = $script:ChildCreated
        child_exit_code = $ExitCode
        child_residual_process_count = 0
        terminal_summary_written = $true
        environment_values_recorded = $false
        packaged_local_channel_verified = $verified
        safe_code = $safeCode
    }
}

function Invoke-EnvironmentTest {
    $assertions = Initialize-SafeProcessEnvironment
    $startInfo = [Diagnostics.ProcessStartInfo]::new()
    $startInfo.UseShellExecute = $false
    $materialized = $null -ne $startInfo.EnvironmentVariables
    $result = [ordered]@{
        schema_version = 1
        environment_test_entered = $true
        environment_assertion_count = $ExpectedEnvironmentAssertionCount
        environment_assertion_passed = $ExpectedEnvironmentAssertionCount
        case_insensitive_duplicate_count = (
            $assertions.case_insensitive_duplicate_count
        )
        path_variant_count = $assertions.path_variant_count
        sensitive_environment_name_count = (
            $assertions.sensitive_environment_name_count
        )
        proxy_environment_name_count = (
            $assertions.proxy_environment_name_count
        )
        redirected_path_outside_repository_count = (
            $assertions.redirected_path_outside_repository_count
        )
        required_redirected_path_count = (
            $assertions.required_redirected_path_count
        )
        process_start_environment_materialized = $materialized
        external_process_created = $false
        executable_creation_count = 0
        environment_values_recorded = $false
        environment_test_passed = $materialized
        safe_code = "packaged_runtime_execution_authorization_required"
    }
    Write-SafeJsonAtomically -Path $EnvironmentResultPath -Document $result
    Write-Output (
        "environment_test_entered=true environment_assertion_passed=9 " +
        "executable_creation_count=0 " +
        "safe_code=packaged_runtime_execution_authorization_required"
    )
}

function Write-StopSignalAtomically {
    $temporaryPath = Join-Path `
        $VerificationRoot `
        (".stop-{0}.part" -f [Guid]::NewGuid().ToString("N"))
    [IO.File]::WriteAllText(
        $temporaryPath,
        "stop" + [Environment]::NewLine,
        [Text.UTF8Encoding]::new($false)
    )
    [IO.File]::Move($temporaryPath, $StopSignalPath)
}

function Invoke-SupervisedChild {
    $process = $null
    $stdoutTask = $null
    $stderrTask = $null
    $creationToken = $null
    $guiWindowObserved = $false
    $innerFailureCategory = "none"
    $innerFailureSafeCode = "none"
    $cleanupFailureCount = 0
    $result = $false
    try {
        if (Test-Path -LiteralPath $VerificationRoot) {
            throw [InvalidOperationException]::new(
                "result_directory_already_exists"
            )
        }
        New-Item `
            -ItemType Directory `
            -Path $VerificationRoot `
            -ErrorAction Stop |
            Out-Null
        Set-SupervisorPhase -Phase "created"
        if ($Mode -ceq "Diagnostic" -and -not $ConfirmDiagnostic) {
            throw [InvalidOperationException]::new(
                "diagnostic_confirmation_required"
            )
        }
        if ($Mode -ceq "Diagnostic" -and $TestFault -cne "None") {
            throw [InvalidOperationException]::new(
                "diagnostic_test_fault_forbidden"
            )
        }
        if ($Mode -ceq "Diagnostic") {
            if (-not (Test-Path -LiteralPath $ExecutablePath -PathType Leaf)) {
                throw [IO.FileNotFoundException]::new(
                    "packaged_executable_unavailable"
                )
            }
            if (Get-Process -Name "SJTUClaw" -ErrorAction SilentlyContinue) {
                throw [InvalidOperationException]::new(
                    "packaged_process_already_running"
                )
            }
        } else {
            if (
                -not (Test-Path -LiteralPath $DummyPowerShellPath -PathType Leaf) -or
                -not (Test-Path -LiteralPath $DummyScriptPath -PathType Leaf)
            ) {
                throw [IO.FileNotFoundException]::new(
                    "dummy_child_unavailable"
                )
            }
        }
        $null = Get-Command "Get-NetTCPConnection" -ErrorAction Stop
        $assertions = Initialize-SafeProcessEnvironment
        if ($assertions.required_redirected_path_count -ne 7) {
            throw [InvalidOperationException]::new(
                "redirected_environment_unavailable"
            )
        }
        Set-SupervisorPhase -Phase "preconditions_validated"

        $startInfo = [Diagnostics.ProcessStartInfo]::new()
        if ($Mode -ceq "Dummy") {
            $startInfo.FileName = $DummyPowerShellPath
            $startInfo.WorkingDirectory = $RepositoryRoot
            $startInfo.Arguments = (
                '-NoLogo -NoProfile -NonInteractive ' +
                '-ExecutionPolicy Bypass -File "{0}" -ControlRoot "{1}"' -f
                $DummyScriptPath,
                $VerificationRoot
            )
        } else {
            $startInfo.FileName = $ExecutablePath
            $startInfo.WorkingDirectory = $DistRoot
        }
        $startInfo.UseShellExecute = $false
        $startInfo.CreateNoWindow = $true
        $startInfo.RedirectStandardOutput = $true
        $startInfo.RedirectStandardError = $true
        $process = [Diagnostics.Process]::new()
        $process.StartInfo = $startInfo
        if (-not $process.Start()) {
            throw [InvalidOperationException]::new(
                "child_process_start_failed"
            )
        }
        $script:ChildPid = $process.Id
        $script:ChildCreated = $true
        $script:ChildRunning = $true
        Set-SupervisorPhase -Phase "child_created"
        $stdoutTask = $process.StandardOutput.ReadToEndAsync()
        $stderrTask = $process.StandardError.ReadToEndAsync()
        $creationToken = [string]$process.StartTime.ToUniversalTime().Ticks
        Set-SupervisorPhase -Phase "child_running"

        while ($true) {
            if ($TestFault -ceq "Wait" -and $script:PollAttemptCount -eq 1) {
                throw [InvalidOperationException]::new("fault_wait")
            }
            $hasExited = $process.WaitForExit(250)
            if ($hasExited) {
                break
            }
            $script:PollAttemptCount += 1
            Set-SupervisorPhase -Phase "observing"
            if ($TestFault -ceq "Refresh") {
                throw [InvalidOperationException]::new("fault_refresh")
            }
            $process.Refresh()
            if ($process.MainWindowHandle -ne [IntPtr]::Zero) {
                $guiWindowObserved = $true
            }
            if (
                ($TestFault -ceq "SamplerFirst" -and
                    $script:PollAttemptCount -eq 1) -or
                ($TestFault -ceq "SamplerMid" -and
                    $script:PollAttemptCount -eq 2)
            ) {
                throw [InvalidOperationException]::new("fault_sampler")
            }
            $rows = @(Get-TcpRowsForProcess -ProcessId $process.Id)
            $script:SuccessfulPollCount += 1
            $timestamp = [DateTime]::UtcNow.ToString(
                "o",
                [Globalization.CultureInfo]::InvariantCulture
            )
            $script:LastSuccessfulPollUtc = $timestamp
            if ($rows.Count -eq 0) {
                Write-RawObservationLine -Document ([ordered]@{
                    schema_version = 1
                    poll_index = $script:PollAttemptCount
                    timestamp_utc = $timestamp
                    child_pid = $script:ChildPid
                    sampler_success = $true
                    sampler_safe_code = "none"
                    endpoint_key = $null
                    flow_key = $null
                    state = "empty"
                    local_address_category = "none"
                    remote_address_category = "none"
                    local_port = 0
                    remote_port = 0
                })
            } else {
                foreach ($row in $rows) {
                    Write-RawObservationLine -Document (
                        Get-SafeEndpointEvidence `
                            -Endpoint $row `
                            -PollIndex $script:PollAttemptCount `
                            -Timestamp $timestamp
                    )
                }
            }
            Write-SafeJsonAtomically `
                -Path $CheckpointPath `
                -Document (Get-SafeCheckpoint)
            if (
                $Mode -ceq "Dummy" -and
                $script:SuccessfulPollCount -ge 3 -and
                -not (Test-Path -LiteralPath $StopSignalPath)
            ) {
                Write-StopSignalAtomically
            }
            if ($TestFault -ceq "Cancel") {
                throw [OperationCanceledException]::new(
                    "fault_cancel"
                )
            }
        }
        $process.WaitForExit()
        $script:ChildRunning = $false
        $script:ChildExitObserved = $true
        Set-SupervisorPhase -Phase "child_exit_observed"
        try {
            $null = $stdoutTask.GetAwaiter().GetResult()
        } catch {
            $cleanupFailureCount += 1
        }
        try {
            $null = $stderrTask.GetAwaiter().GetResult()
        } catch {
            $cleanupFailureCount += 1
        }
        $pidReuseDetected = $false
        $replacement = Get-Process `
            -Id $process.Id `
            -ErrorAction SilentlyContinue
        if ($null -ne $replacement) {
            $replacementToken = [string](
                $replacement.StartTime.ToUniversalTime().Ticks
            )
            $pidReuseDetected = $replacementToken -cne $creationToken
        }
        $postExitRows = @(Get-TcpRowsForProcess -ProcessId $process.Id)
        $endpointsDisappeared = $postExitRows.Count -eq 0
        Set-SupervisorPhase -Phase "finalizing"
        $summary = Get-DiagnosticSummaryFromDisk `
            -ProcessExitObserved $true `
            -EndpointsDisappearedAfterExit $endpointsDisappeared `
            -PidReuseDetected $pidReuseDetected `
            -GuiWindowObserved $guiWindowObserved `
            -ExitCode $process.ExitCode
        if ($TestFault -ceq "SummaryWrite") {
            throw [IO.IOException]::new("fault_summary_write")
        }
        Write-SafeJsonAtomically -Path $SummaryPath -Document $summary
        $script:TerminalSummaryWritten = $true
        if ($TestFault -ceq "Finalize") {
            throw [InvalidOperationException]::new("fault_finalize")
        }
        $script:SupervisorSafeCode = $summary.safe_code
        $result = (
            ($Mode -ceq "Dummy" -and $process.ExitCode -eq 0) -or
            (
                $Mode -ceq "Diagnostic" -and
                $summary.packaged_local_channel_verified
            )
        )
    } catch {
        $innerFailureCategory = Get-SafeExceptionCategory `
            -Exception $_.Exception
        $innerFailureSafeCode = (
            "packaged_runtime_supervisor_{0}_failed" -f
            $innerFailureCategory
        )
        $script:SupervisorSafeCode = $innerFailureSafeCode
        try {
            Write-RawObservationLine -Document ([ordered]@{
                schema_version = 1
                poll_index = $script:PollAttemptCount
                timestamp_utc = [DateTime]::UtcNow.ToString(
                    "o",
                    [Globalization.CultureInfo]::InvariantCulture
                )
                child_pid = $script:ChildPid
                sampler_success = $false
                sampler_safe_code = $innerFailureSafeCode
                endpoint_key = $null
                flow_key = $null
                state = "supervisor_failure"
                local_address_category = "none"
                remote_address_category = "none"
                local_port = 0
                remote_port = 0
            })
        } catch {
            $cleanupFailureCount += 1
        }
        try {
            Set-SupervisorPhase -Phase "supervisor_failed"
        } catch {
            $cleanupFailureCount += 1
        }
    } finally {
        if ($null -ne $process -and $script:ChildCreated) {
            $stillRunning = $false
            try {
                $process.Refresh()
                $stillRunning = -not $process.HasExited
                $script:ChildRunning = $stillRunning
            } catch {
                $cleanupFailureCount += 1
                $stillRunning = $true
            }
            if ($stillRunning -and $Mode -ceq "Dummy") {
                try {
                    if (-not (Test-Path -LiteralPath $StopSignalPath)) {
                        Write-StopSignalAtomically
                    }
                } catch {
                    $cleanupFailureCount += 1
                }
                try {
                    if (-not $process.WaitForExit(5000)) {
                        $process.Kill()
                        $process.WaitForExit(5000)
                    }
                    $script:ChildRunning = -not $process.HasExited
                    $script:ChildExitObserved = $process.HasExited
                } catch {
                    $cleanupFailureCount += 1
                }
            }
            if ($stillRunning -and $Mode -ceq "Diagnostic") {
                try {
                    while (-not $process.WaitForExit(250)) {
                        $script:ChildRunning = $true
                    }
                    $script:ChildRunning = $false
                    $script:ChildExitObserved = $true
                } catch {
                    $cleanupFailureCount += 1
                }
            }
            try {
                $process.Dispose()
            } catch {
                $cleanupFailureCount += 1
            }
        }
        if ($cleanupFailureCount -gt 0 -and $result) {
            $result = $false
            $innerFailureCategory = "cleanup"
            $innerFailureSafeCode = (
                "packaged_runtime_supervisor_cleanup_failed"
            )
            $script:SupervisorSafeCode = $innerFailureSafeCode
        }
        if ($result) {
            try {
                Set-SupervisorPhase -Phase "completed"
            } catch {
                $result = $false
                $cleanupFailureCount += 1
                $innerFailureCategory = "cleanup"
                $innerFailureSafeCode = (
                    "packaged_runtime_supervisor_cleanup_failed"
                )
                $script:SupervisorSafeCode = $innerFailureSafeCode
            }
        }
        if (-not $result) {
            $terminalFailure = [ordered]@{
                schema_version = 1
                supervisor_phase = "supervisor_failed"
                failed_phase = $script:SupervisorPhase
                fixed_exception_category = $innerFailureCategory
                child_pid = $script:ChildPid
                child_created = $script:ChildCreated
                child_running = $script:ChildRunning
                child_exit_observed = $script:ChildExitObserved
                poll_attempt_count = $script:PollAttemptCount
                successful_poll_count = $script:SuccessfulPollCount
                raw_observation_count = $script:RawObservationCount
                cleanup_failure_count = $cleanupFailureCount
                terminal_summary_written = $true
                environment_values_recorded = $false
                safe_code = $innerFailureSafeCode
            }
            try {
                Write-SafeJsonAtomically `
                    -Path $SummaryPath `
                    -Document $terminalFailure
                $script:TerminalSummaryWritten = $true
            } catch {
                $cleanupFailureCount += 1
            }
            try {
                Write-SafeJsonAtomically `
                    -Path $CheckpointPath `
                    -Document (Get-SafeCheckpoint)
            } catch {
                $cleanupFailureCount += 1
            }
        }
    }
    if ($result) {
        $script:SupervisorOutputLine = (
            "supervisor_complete=true mode={0} poll_attempt_count={1} " +
            "successful_poll_count={2} raw_observation_count={3} " +
            "safe_code={4}" -f
            $Mode,
            $script:PollAttemptCount,
            $script:SuccessfulPollCount,
            $script:RawObservationCount,
            $script:SupervisorSafeCode
        )
    } else {
        $script:SupervisorOutputLine = $innerFailureSafeCode
    }
    return $result
}

try {
    if ($Mode -ceq "EnvironmentTest") {
        Invoke-EnvironmentTest
        exit 0
    }
    $completed = Invoke-SupervisedChild
    Write-Output $SupervisorOutputLine
    exit $(if ($completed) { 0 } else { 2 })
} catch {
    $safeCode = if ($Mode -ceq "EnvironmentTest") {
        "packaged_runtime_launcher_environment_failed"
    } elseif (
        $_.Exception.Message -ceq "diagnostic_confirmation_required"
    ) {
        "packaged_runtime_diagnostic_confirmation_required"
    } else {
        "packaged_runtime_diagnostic_failed"
    }
    Write-Output $safeCode
    exit 2
}
