# Host-side telemetry, for the half of the system the GPU counters cannot see.
#
#   host-telemetry.ps1 -Tag <name> [-IntervalSec 2]
#
# WHY. nvidia-smi answers questions about the GPU. A person designing a CPU, a
# PCH, an SoC or an accelerator needs the rest of the machine, and local
# inference stresses it in ways the GPU counters give no hint of. A first
# sample during agentic code repair, with the GPU at 90% busy:
#
#     CPU 8.4% busy        <- the host is nearly idle in aggregate
#     privileged 4.2%      <- but HALF of what it does spend is kernel time
#     197,710 syscalls/s   <- an enormous rate for an "idle" CPU
#     57,781 ctx switches/s
#     28,798 page faults/s <- the mmap'd weights being walked
#     3,314 MB free        <- with the model resident, headroom is thin
#
# Aggregate CPU utilisation is the WRONG number here and that is the point:
# 8.4% of 20 threads hides a single-threaded orchestration loop making two
# hundred thousand syscalls a second. A designer reading only "CPU 8%" would
# conclude the host is free; the syscall and context-switch rates say the
# opposite about latency sensitivity, and this campaign has already measured
# that loading the host costs 5.4% of GPU decode throughput while the GPU
# clock RISES - a coupling invisible from either side alone.
#
# WHAT IS SAMPLED, and what each is for:
#   % Processor Time / % Privileged   user against kernel split
#   % Processor Time per core         whether the load is one thread or many
#   Context Switches/sec              scheduler pressure
#   System Calls/sec                  host-side driver and runtime overhead
#   Available MBytes                  capacity headroom with weights resident
#   Page Faults/sec                   mmap behaviour while weights are walked
#   Pages Input/sec                   actual paging FROM DISK, the painful kind
#   Disk Bytes/sec, Avg Disk Queue    storage pressure during load and spill
#   Interrupts/sec                    device interrupt load
#
# Written as CSV with a unix timestamp so it joins the GPU dmon stream on time.
param(
    [Parameter(Mandatory=$true)][string]$Tag,
    [double]$IntervalSec = 2.0,
    [string]$OutDir = "E:\AI\measured-inference\results\qwen38-27b-blind\data\telemetry"
)

New-Item -ItemType Directory -Force -Path $OutDir | Out-Null
$csv = Join-Path $OutDir "$Tag-host.csv"

$counters = @(
    '\Processor Information(_Total)\% Processor Time',
    '\Processor Information(_Total)\% Privileged Time',
    '\Processor Information(_Total)\% User Time',
    '\System\Context Switches/sec',
    '\System\System Calls/sec',
    '\System\Processor Queue Length',
    '\Memory\Available MBytes',
    '\Memory\Page Faults/sec',
    '\Memory\Pages Input/sec',
    '\Memory\Committed Bytes',
    '\PhysicalDisk(_Total)\Disk Bytes/sec',
    '\PhysicalDisk(_Total)\Avg. Disk Queue Length',
    '\Processor Information(_Total)\Interrupts/sec'
)

"t,cpu_pct,priv_pct,user_pct,ctxsw_s,syscalls_s,runq,avail_mb,pagefaults_s,pagesin_s,committed_bytes,disk_bytes_s,disk_qlen,interrupts_s" |
    Out-File -FilePath $csv -Encoding utf8

Write-Output "host telemetry -> $csv (interval ${IntervalSec}s)"

while ($true) {
    try {
        $s = (Get-Counter -Counter $counters -ErrorAction Stop).CounterSamples
        $t = [Math]::Round((Get-Date -UFormat %s), 3)
        # F2 with InvariantCulture, NOT N2: N2 inserts thousands separators, so
        # a context-switch rate of 46505.33 is written "46,505.33" and splits
        # into two CSV columns, silently shifting every field after it. Caught
        # on the first sample; it would otherwise have produced a file that
        # parses without error and means nothing.
        $inv = [System.Globalization.CultureInfo]::InvariantCulture
        $v = ($s | ForEach-Object { $_.CookedValue.ToString("F2", $inv) }) -join ','
        "$t,$v" | Out-File -FilePath $csv -Encoding utf8 -Append
    } catch { }
    Start-Sleep -Seconds $IntervalSec
}
