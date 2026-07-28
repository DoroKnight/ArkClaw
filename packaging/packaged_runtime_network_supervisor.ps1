param(
    [ValidateSet("Disabled", "EnvironmentTest", "Diagnostic")]
    [string]$Mode = "Disabled",

    [switch]$ConfirmDiagnostic
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
$VerificationRoot = Join-Path `
    $RepositoryRoot `
    "build\packaged-runtime-network-diagnostic"
$DistRoot = Join-Path $RepositoryRoot "dist\SJTUClaw.dist"
$ExecutablePath = Join-Path $DistRoot "SJTUClaw.exe"
$EnvironmentResultPath = Join-Path $VerificationRoot "environment-test.json"
$RawObservationPath = Join-Path $VerificationRoot "tcp-observations.json"
$SummaryPath = Join-Path $VerificationRoot "diagnostic-summary.json"
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
        (".evidence-{0}.tmp" -f [Guid]::NewGuid().ToString("N"))
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
        [IO.File]::Replace($temporaryPath, $Path, $null)
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

function Invoke-PackagedDiagnostic {
    if (-not $ConfirmDiagnostic) {
        throw [InvalidOperationException]::new(
            "diagnostic_confirmation_required"
        )
    }
    if (-not (Test-Path -LiteralPath $ExecutablePath -PathType Leaf)) {
        throw [IO.FileNotFoundException]::new(
            "packaged_executable_unavailable"
        )
    }
    if (
        Get-Process -Name "SJTUClaw" -ErrorAction SilentlyContinue
    ) {
        throw [InvalidOperationException]::new(
            "packaged_process_already_running"
        )
    }
    $null = Get-Command "Get-NetTCPConnection" -ErrorAction Stop
    $assertions = Initialize-SafeProcessEnvironment
    if ($assertions.required_redirected_path_count -ne 7) {
        throw [InvalidOperationException]::new(
            "redirected_environment_unavailable"
        )
    }

    $startInfo = [Diagnostics.ProcessStartInfo]::new()
    $startInfo.FileName = $ExecutablePath
    $startInfo.WorkingDirectory = $DistRoot
    $startInfo.UseShellExecute = $false
    $startInfo.CreateNoWindow = $true
    $startInfo.RedirectStandardOutput = $true
    $startInfo.RedirectStandardError = $true
    $process = [Diagnostics.Process]::new()
    $process.StartInfo = $startInfo
    if (-not $process.Start()) {
        throw [InvalidOperationException]::new(
            "packaged_process_start_failed"
        )
    }
    $stdoutTask = $process.StandardOutput.ReadToEndAsync()
    $stderrTask = $process.StandardError.ReadToEndAsync()
    $creationToken = [string]$process.StartTime.ToUniversalTime().Ticks
    $observations = [Collections.Generic.Dictionary[string,object]]::new(
        [StringComparer]::Ordinal
    )
    $pollCount = 0
    $sampleCount = 0
    $guiWindowObserved = $false
    while (-not $process.WaitForExit(250)) {
        $pollCount += 1
        $process.Refresh()
        if ($process.MainWindowHandle -ne [IntPtr]::Zero) {
            $guiWindowObserved = $true
        }
        $rows = @(Get-TcpRowsForProcess -ProcessId $process.Id)
        $sampleCount += Add-TcpObservationPoll `
            -Observations $observations `
            -Endpoints $rows `
            -PollNumber $pollCount
    }
    $process.WaitForExit()
    $null = $stdoutTask.GetAwaiter().GetResult()
    $null = $stderrTask.GetAwaiter().GetResult()

    $pidReuseDetected = $false
    $replacement = Get-Process -Id $process.Id -ErrorAction SilentlyContinue
    if ($null -ne $replacement) {
        $replacementToken = [string]$replacement.StartTime.ToUniversalTime().Ticks
        $pidReuseDetected = $replacementToken -cne $creationToken
    }
    $postExitRows = @(Get-TcpRowsForProcess -ProcessId $process.Id)
    $endpointsDisappeared = $postExitRows.Count -eq 0
    $rawDocument = [ordered]@{
        schema_version = 1
        observer_authority = "Get-NetTCPConnection"
        process_id = $process.Id
        poll_count = $pollCount
        sample_count = $sampleCount
        endpoint_count = $observations.Count
        endpoints = @($observations.Values)
        environment_values_recorded = $false
    }
    $summary = Get-DiagnosticSummary `
        -Observations $observations `
        -PollCount $pollCount `
        -SampleCount $sampleCount `
        -ProcessExitObserved $true `
        -EndpointsDisappearedAfterExit $endpointsDisappeared `
        -PidReuseDetected $pidReuseDetected `
        -GuiWindowObserved $guiWindowObserved `
        -ExitCode $process.ExitCode
    Write-SafeJsonAtomically -Path $RawObservationPath -Document $rawDocument
    Write-SafeJsonAtomically -Path $SummaryPath -Document $summary
    Write-Output (
        "poll_count={0} sample_count={1} unique_endpoint_count={2} " +
        "bound_endpoint_count={3} established_endpoint_count={4} " +
        "external_endpoint_count={5} unattributed_endpoint_count={6} " +
        "safe_code={7}" -f
        $summary.poll_count,
        $summary.sample_count,
        $summary.unique_endpoint_count,
        $summary.bound_endpoint_count,
        $summary.established_endpoint_count,
        $summary.external_endpoint_count,
        $summary.unattributed_endpoint_count,
        $summary.safe_code
    )
    if (-not $summary.packaged_local_channel_verified) {
        exit 2
    }
}

try {
    if ($Mode -ceq "EnvironmentTest") {
        Invoke-EnvironmentTest
        exit 0
    }
    Invoke-PackagedDiagnostic
    exit 0
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
