<#
.SYNOPSIS
    Start / stop / list the detached 500 ms nvidia-smi board-power CSV logger.

.DESCRIPTION
    Tier: in-band GPU board power (NVML, via nvidia-smi). PSU losses, the rest
    of the node, and PUE are NOT in this number and are unmeasured unless a
    wall meter is logged separately.

    The logger is one detached nvidia-smi process sampling at -lms 500 into a
    CSV. It costs ~one process and a few MB/day and it retroactively converts
    every benchmark that ran while it was up into an energy arm.

    SAFETY CONTRACT (the reason -Stop looks paranoid):
      * -Stop NEVER kills by process name. It requires an explicit target and
        it verifies, over WMI/CIM, that the target really is an nvidia-smi
        telemetry loop before touching it.
      * A logger is selected by the CSV path it writes. -Start puts that path
        into nvidia-smi's own command line (-f) AND drops a sidecar
        (<csv>.logger.json) recording the pid. -Stop matches on those two, in
        that order - and on the sidecar only while it still says running=true.
      * Consequence, stated plainly: a logger somebody started by hand with
        shell redirection (`nvidia-smi ... > foo.csv`) carries NO path in its
        command line and has no sidecar, so -Stop can never find it and can
        never kill it, whatever CSV path you pass. Use -List to see its pid and
        -Stop -ProcessId <pid> to end it deliberately.

    THE SIDECAR IS RETIRED, NOT DELETED (rule 28; changed 2026-08-31):
      -Stop used to Remove-Item this file the moment it had killed something,
      on the reasoning that it is the lock of a running logger. It is a lock,
      but it is mostly a RECORD: mode, interval_ms, query, tier and
      started_iso are conditions of the run (rule 3) that the CSV rows do not
      carry, and its POSIX twin sample-power.sh writes seven more into the
      same file - enforced_power_limit_w above all, the board cap in force
      when the log began, which silently rescales every watt in the CSV and
      cannot be read back out of it. Rule 28: a field not written down during
      the run cannot be recovered at any price. This one WAS written down, and
      was then destroyed at the exact moment the CSV became an artefact -
      measured with the POSIX twin on this repo's Ubuntu box on 2026-08-31,
      where a start/stop cycle left a 43-row CSV and no sidecar at all.
      -Stop now REWRITES the record instead: every key it already carried,
      running=false, and a stopped_iso. Only after a kill it counted - a
      logger that survived -Stop is still running, and its record has to go on
      saying so or the retry cannot find it. Two consequences worth holding:
        - a sidecar now outlives its logger BY DESIGN, so route 2 in
          Find-LoggersForCsv skips any record whose running is false. Deleting
          the file used to guarantee that for free; the guard buys it back,
          and it matters because route 2 verifies only that the recorded pid
          is an nvidia-smi loop NOW, never that it is writing THIS csv.
        - a record with NO running key is every sidecar written before
          2026-08-31, on either platform, and is read as live exactly as it
          was before this change.
      -Start's record gains that one key: nine keys, now ten, and eleven once
      a stopped_iso joins it. sample-power.sh writes the same ten plus its
      seven, so its record stays the superset this one can always read.

.PARAMETER Csv
    Output CSV path. Required for -Start and for -Stop.

.PARAMETER IntervalMs
    Sample period in ms. Default 500.

.PARAMETER Force
    -Start: overwrite an existing CSV / start a second logger for the same path.

.PARAMETER ProcessId
    -Stop: stop this exact pid, after verifying it is an nvidia-smi query loop.
    The deliberate escape hatch for loggers this script did not start.

.EXAMPLE
    .\sample-power.ps1 -Start -Csv results\<slug>\data\power\campaign-power.csv
.EXAMPLE
    .\sample-power.ps1 -List
.EXAMPLE
    .\sample-power.ps1 -Stop -Csv results\<slug>\data\power\campaign-power.csv
#>
[CmdletBinding(DefaultParameterSetName = 'Start')]
param(
    [Parameter(ParameterSetName = 'Start')]
    [switch]$Start,

    [Parameter(ParameterSetName = 'Stop', Mandatory = $true)]
    [switch]$Stop,

    [Parameter(ParameterSetName = 'List', Mandatory = $true)]
    [switch]$List,

    [Parameter(ParameterSetName = 'Start')]
    [Parameter(ParameterSetName = 'Stop')]
    [string]$Csv,

    [Parameter(ParameterSetName = 'Start')]
    [int]$IntervalMs = 500,

    [Parameter(ParameterSetName = 'Start')]
    [switch]$Force,

    [Parameter(ParameterSetName = 'Start')]
    [int]$VerifySeconds = 8,

    [Parameter(ParameterSetName = 'Stop')]
    [int]$ProcessId = 0
)

$ErrorActionPreference = 'Stop'

# The query. clocks / pstate / util are in here on purpose: they are how you
# prove a low-watt sample was a RAMPING board and not an efficient one.
$script:SCRIPTNAME = 'sample-power.ps1'
$script:QUERY = 'timestamp,power.draw,power.draw.instant,clocks.sm,clocks.mem,' +
                'utilization.gpu,utilization.memory,memory.used,memory.reserved,' +
                'temperature.gpu,pstate'

function Resolve-OutPath {
    param([string]$Path)
    if ([string]::IsNullOrWhiteSpace($Path)) { return $null }
    $dir = Split-Path -Parent $Path
    if ([string]::IsNullOrWhiteSpace($dir)) { $dir = (Get-Location).Path }
    if (-not (Test-Path -LiteralPath $dir)) {
        New-Item -ItemType Directory -Path $dir -Force | Out-Null
    }
    $full = Join-Path (Resolve-Path -LiteralPath $dir).Path (Split-Path -Leaf $Path)
    return $full
}

function Get-LoggerProcesses {
    # Every nvidia-smi telemetry loop on the box. Read-only; never kills.
    $out = @()
    try {
        $procs = Get-CimInstance Win32_Process -Filter "Name='nvidia-smi.exe'" -ErrorAction Stop
    } catch {
        Write-Host "  WARN could not query Win32_Process: $($_.Exception.Message)"
        return $out
    }
    foreach ($p in $procs) {
        $cl = [string]$p.CommandLine
        if ($cl -eq '') { continue }
        # A logger = a query loop. Anything else that happens to be nvidia-smi
        # (a one-shot --query-gpu, nvidia-smi -q from another tool) is skipped.
        $isLoop = ($cl.IndexOf('--query-gpu', [StringComparison]::OrdinalIgnoreCase) -ge 0) -and
                  (($cl.IndexOf('-lms', [StringComparison]::OrdinalIgnoreCase) -ge 0) -or
                   ($cl.IndexOf(' -l ', [StringComparison]::OrdinalIgnoreCase) -ge 0))
        if (-not $isLoop) { continue }
        $out += [pscustomobject]@{
            ProcessId   = [int]$p.ProcessId
            CommandLine = $cl
            Started     = $p.CreationDate
        }
    }
    return $out
}

function Get-SidecarPath { param([string]$FullCsv) return "$FullCsv.logger.json" }

function Find-LoggersForCsv {
    # Selection is by CSV path, two independent routes, both verified.
    param([string]$FullCsv)
    $hits = @{}
    $all = Get-LoggerProcesses

    # Route 1: the path is in nvidia-smi's own command line (-f <csv>).
    foreach ($p in $all) {
        if ($p.CommandLine.IndexOf($FullCsv, [StringComparison]::OrdinalIgnoreCase) -ge 0) {
            $hits[$p.ProcessId] = [pscustomobject]@{ Proc = $p; Via = 'cmdline' }
        }
    }

    # Route 2: the sidecar lock file this script wrote next to the CSV.
    $side = Get-SidecarPath $FullCsv
    if (Test-Path -LiteralPath $side) {
        $rec = $null
        try { $rec = Get-Content -LiteralPath $side -Raw -Encoding UTF8 | ConvertFrom-Json } catch { $rec = $null }
        # A RETIRED record is not a route (rule 28, 2026-08-31). -Stop no
        # longer deletes this file, it rewrites it with running=false, so a
        # sidecar outlives its logger by design now and the pid in a retired
        # one is history. That pid is recycled sooner or later, the check
        # below asks only whether it is an nvidia-smi query loop NOW and never
        # whether it is writing THIS csv, and a match here is something -Stop
        # kills: without this guard a finished phase's record could hand -Stop
        # a live logger belonging to a different CSV. The POSIX twin was
        # reproduced doing exactly that on 2026-08-30 and dropped this route
        # entirely; Windows cannot, because for a -Start that fell back to
        # redirection the sidecar is the only handle there is.
        # A record with no running key - every sidecar written before
        # 2026-08-31 - is not retired and is treated as live, exactly as it
        # was before this change.
        $retired = ($null -ne $rec) -and ($null -ne $rec.running) -and (-not $rec.running)
        if ($null -ne $rec -and $rec.pid -and -not $retired) {
            $pidv = [int]$rec.pid
            $match = $all | Where-Object { $_.ProcessId -eq $pidv } | Select-Object -First 1
            if ($null -ne $match -and -not $hits.ContainsKey($pidv)) {
                # Verified: that pid is currently an nvidia-smi query loop, not
                # some unrelated process that inherited a recycled pid.
                $hits[$pidv] = [pscustomobject]@{ Proc = $match; Via = 'sidecar' }
            }
        }
    }
    return @($hits.Values)
}

function Get-CsvDataLineCount {
    param([string]$Path)
    if (-not (Test-Path -LiteralPath $Path)) { return -1 }
    try {
        $n = @(Get-Content -LiteralPath $Path -ErrorAction Stop).Count
        return $n
    } catch {
        return -1   # locked or unreadable
    }
}

function Start-Logger {
    param([string]$FullCsv, [int]$Ms, [switch]$Overwrite, [int]$Verify)

    $existing = Find-LoggersForCsv $FullCsv
    if ($existing.Count -gt 0 -and -not $Overwrite) {
        Write-Host "REFUSED a logger is already writing that CSV:"
        foreach ($e in $existing) {
            Write-Host "  pid=$($e.Proc.ProcessId) via=$($e.Via) started=$($e.Proc.Started)"
        }
        Write-Host "  Use -Force to start a second one, or -Stop -Csv <path> first."
        return $null
    }
    if ((Test-Path -LiteralPath $FullCsv) -and -not $Overwrite) {
        $sz = (Get-Item -LiteralPath $FullCsv).Length
        if ($sz -gt 0) {
            Write-Host "REFUSED $FullCsv already exists ($sz bytes)."
            Write-Host "  One file per phase is the convention - pick a new name, or pass -Force to overwrite."
            return $null
        }
    }

    $errLog = "$FullCsv.stderr.log"
    # Mode A: -f puts the destination path into nvidia-smi's own command line,
    # which is what makes -Stop's WMI match exact.
    $argsA = @("--query-gpu=$($script:QUERY)", '--format=csv,nounits', '-lms', "$Ms", '-f', $FullCsv)
    Write-Host "START nvidia-smi --query-gpu=... --format=csv,nounits -lms $Ms -f `"$FullCsv`""
    $proc = Start-Process -FilePath 'nvidia-smi' -ArgumentList $argsA -WindowStyle Hidden `
                          -RedirectStandardError $errLog -PassThru
    $mode = 'filename'

    # Verify it is actually producing readable, growing output. If nvidia-smi's
    # -f buffers or locks the file on this driver, the log is useless for live
    # reads, so fall back to the stdout-redirection form that this machine's
    # campaign already proved streams line-by-line.
    $ok = $false
    for ($i = 0; $i -lt ($Verify * 2); $i++) {
        Start-Sleep -Milliseconds 500
        if ($proc.HasExited) { break }
        if ((Get-CsvDataLineCount $FullCsv) -ge 3) { $ok = $true; break }
    }
    if (-not $ok) {
        Write-Host "  -f mode did not produce a readable growing CSV; falling back to stdout redirection."
        if (-not $proc.HasExited) {
            try { Stop-Process -Id $proc.Id -Force -Confirm:$false } catch {}
        }
        Start-Sleep -Milliseconds 300
        $argsB = @("--query-gpu=$($script:QUERY)", '--format=csv,nounits', '-lms', "$Ms")
        $proc = Start-Process -FilePath 'nvidia-smi' -ArgumentList $argsB -WindowStyle Hidden `
                              -RedirectStandardOutput $FullCsv -RedirectStandardError $errLog -PassThru
        $mode = 'redirect'
        for ($i = 0; $i -lt ($Verify * 2); $i++) {
            Start-Sleep -Milliseconds 500
            if ($proc.HasExited) { break }
            if ((Get-CsvDataLineCount $FullCsv) -ge 3) { $ok = $true; break }
        }
    }

    $rec = [pscustomobject]@{
        pid          = $proc.Id
        csv          = $FullCsv
        mode         = $mode
        interval_ms  = $Ms
        query        = $script:QUERY
        started_iso  = (Get-Date).ToString('yyyy-MM-ddTHH:mm:ss.fff')
        started_by   = "$($script:SCRIPTNAME) on $env:COMPUTERNAME"
        tier         = 'in-band GPU board power (NVML); PSU/wall/PUE excluded'
        verified     = [bool]$ok
        # The lifecycle, recorded at both ends of the run: true here, false in
        # a stopped_iso-bearing record once -Stop retires this file instead of
        # deleting it (rule 28 - see the header). Written at start so the flag
        # is a statement the record makes about itself rather than something a
        # reader has to infer from a missing key, and so Find-LoggersForCsv's
        # route 2 has one property to test rather than two states to guess
        # between. sample-power.sh writes the same key, same spelling.
        running      = $true
    }
    $side = Get-SidecarPath $FullCsv
    $rec | ConvertTo-Json -Depth 5 | Out-File -FilePath $side -Encoding utf8

    if ($ok) {
        Write-Host "OK    pid=$($proc.Id) mode=$mode interval=${Ms}ms -> $FullCsv"
    } else {
        Write-Host "WARN  pid=$($proc.Id) mode=$mode started but no samples were readable within ${Verify}s."
        Write-Host "      Check $errLog and that nvidia-smi is on PATH."
    }
    Write-Host "      sidecar: $side"
    Write-Host "      NOTE clock-ramp: the first samples after an idle board read LOW because the"
    Write-Host "      SM clock is still ramping (measured here: ~900-990 MHz vs 1455 settled). Warm"
    Write-Host "      the GPU with a throwaway request before any arm you intend to publish."
    return $rec
}

function Set-SidecarRetired {
    # Start-Logger's record, rewritten at the end of the run instead of
    # deleted - the header's THE SIDECAR IS RETIRED, NOT DELETED says why, and
    # rule 28 is the whole of it. The round trip is the one route 2 already
    # does (Get-Content -Raw | ConvertFrom-Json), so every key the record
    # carries survives it, including the seven that only sample-power.sh
    # writes - gpu_name, driver_version, enforced_power_limit_w, gpu_index,
    # euid, elevated, stderr_log - which this script never produces and must
    # never drop when it is handed a POSIX record. -Force on Add-Member
    # overwrites the running that -Start wrote rather than failing on it, and
    # is also what makes retiring an already-retired record a no-op.
    # $false on any refusal, with the record left exactly as it was: a stale
    # lifecycle line is a wrong sentence, a deleted record is a lost
    # measurement, and only the first can be corrected by reading the file.
    param([string]$Side)
    if (-not (Test-Path -LiteralPath $Side)) { return $false }
    $rec = $null
    try { $rec = Get-Content -LiteralPath $Side -Raw -Encoding UTF8 | ConvertFrom-Json } catch { $rec = $null }
    if ($null -eq $rec) { return $false }
    try {
        $rec | Add-Member -NotePropertyName 'running' -NotePropertyValue $false -Force
        $rec | Add-Member -NotePropertyName 'stopped_iso' `
                          -NotePropertyValue ((Get-Date).ToString('yyyy-MM-ddTHH:mm:ss.fff')) -Force
        $rec | ConvertTo-Json -Depth 5 | Out-File -FilePath $Side -Encoding utf8
    } catch {
        return $false
    }
    return $true
}

function Stop-LoggerByCsv {
    param([string]$FullCsv)
    $hits = Find-LoggersForCsv $FullCsv
    if ($hits.Count -eq 0) {
        Write-Host "NONE  no logger found writing $FullCsv"
        Write-Host "      (A logger started by hand with shell redirection carries no path in its"
        Write-Host "      command line and has no sidecar - it is invisible here BY DESIGN. Run"
        Write-Host "      -List to see every nvidia-smi loop and stop it with -Stop -ProcessId <pid>.)"
        return 0
    }
    $n = 0
    foreach ($h in $hits) {
        Write-Host "STOP  pid=$($h.Proc.ProcessId) via=$($h.Via) started=$($h.Proc.Started)"
        try {
            Stop-Process -Id $h.Proc.ProcessId -Force -Confirm:$false
            $n++
        } catch {
            Write-Host "  FAILED $($_.Exception.Message)"
        }
    }
    Write-Host "OK    stopped $n logger(s); CSV left in place: $FullCsv"
    # RETIRED, NOT DELETED (rule 28) - the header section of that name carries
    # the reasoning and the measurement. Only when a kill above actually
    # counted: writing running=false over a logger that survived -Stop would
    # be a false record AND would make route 2 skip it, which is the one way
    # this change could lose a live logger instead of preserving a dead one's
    # conditions. Remove-Item ran unconditionally here; retirement does not.
    $side = Get-SidecarPath $FullCsv
    if ($n -gt 0 -and (Test-Path -LiteralPath $side)) {
        if (Set-SidecarRetired -Side $side) {
            Write-Host "      sidecar retired, not deleted: $side"
            Write-Host "      It now reads running=false with a stopped_iso, and it still carries the"
            Write-Host "      conditions the CSV rows cannot - keep the two together."
        } else {
            Write-Host "WARN  could not retire the sidecar $side - it is unchanged, so nothing in it"
            Write-Host "      marks this logger as stopped. Its conditions are intact and readable;"
            Write-Host "      only its lifecycle is now stale."
        }
    }
    return $n
}

function Stop-LoggerByPid {
    param([int]$TargetPid)
    $match = Get-LoggerProcesses | Where-Object { $_.ProcessId -eq $TargetPid } | Select-Object -First 1
    if ($null -eq $match) {
        Write-Host "REFUSED pid $TargetPid is not a running nvidia-smi telemetry loop. Nothing killed."
        return 0
    }
    Write-Host "STOP  pid=$TargetPid (explicit) started=$($match.Started)"
    Write-Host "      $($match.CommandLine)"
    try {
        Stop-Process -Id $TargetPid -Force -Confirm:$false
        Write-Host "OK    stopped 1 logger."
        return 1
    } catch {
        Write-Host "  FAILED $($_.Exception.Message)"
        return 0
    }
}

function Show-Loggers {
    $all = Get-LoggerProcesses
    if ($all.Count -eq 0) { Write-Host "no nvidia-smi telemetry loops running"; return }
    Write-Host "nvidia-smi telemetry loops currently running:"
    foreach ($p in $all) {
        $target = '(stdout redirect - destination not visible in the command line)'
        # -f must be a standalone flag: do not match the "-f" inside "--format=".
        $m = [regex]::Match($p.CommandLine, '(?:\s-f\s+|\s--filename=)"?([^"]+?)"?\s*$')
        if ($m.Success) { $target = $m.Groups[1].Value }
        Write-Host ""
        Write-Host "  pid     : $($p.ProcessId)"
        Write-Host "  started : $($p.Started)"
        Write-Host "  writes  : $target"
        Write-Host "  cmdline : $($p.CommandLine.Trim())"
    }
    Write-Host ""
    Write-Host "Stop one with:  -Stop -Csv <its csv>   (if this script started it)"
    Write-Host "            or: -Stop -ProcessId <pid> (explicit, verified, never by name)"
}

# ---------------------------------------------------------------- dispatch
if ($List) {
    Show-Loggers
    return
}

if ($Stop) {
    if ($ProcessId -gt 0) {
        Stop-LoggerByPid -TargetPid $ProcessId | Out-Null
        return
    }
    if ([string]::IsNullOrWhiteSpace($Csv)) {
        Write-Host "REFUSED -Stop needs an explicit target: -Csv <path> or -ProcessId <pid>."
        Write-Host "        This script will not stop loggers by process name."
        return
    }
    $full = Resolve-OutPath $Csv
    Stop-LoggerByCsv -FullCsv $full | Out-Null
    return
}

# default: -Start
if ([string]::IsNullOrWhiteSpace($Csv)) {
    Write-Host "REFUSED -Start needs -Csv <path>."
    Write-Host "        e.g. .\sample-power.ps1 -Start -Csv results\<slug>\data\power\campaign-power.csv"
    return
}
$full = Resolve-OutPath $Csv
Start-Logger -FullCsv $full -Ms $IntervalMs -Overwrite:$Force -Verify $VerifySeconds | Out-Null
