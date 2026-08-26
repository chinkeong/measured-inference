# Launch one arm of the agentic benchmark with COMPLETE instrumentation.
#
#   run-agentic-arm.ps1 -Model <path.gguf> -Tag <name> [-Port 1283] [-NumTests -1]
#
# WHY THIS SCRIPT EXISTS. The first full agentic run of this campaign was
# started by hand and lost two things it could never get back: the server was
# launched without `--metrics`, and its stdout went to a file that stayed 0
# bytes for two hours. The result was a complete GPU power trace and complete
# pass rates that COULD NOT BE DIVIDED INTO EACH OTHER - joules were known,
# tokens were not. Recovering even part of it took a client-side join whose
# first version was wrong in a way that inflated a published figure tenfold.
#
# A run costs three to four hours. Every field below is free at launch and
# unobtainable afterwards, so the launcher collects all of them, and it starts
# the samplers BEFORE the benchmark so the window is complete from the first
# exercise rather than from whenever someone remembered.
#
# WHAT IS COLLECTED, and which question each one answers:
#   dmon + throttle   power, clocks, SM and memory utilisation, VRAM, PCIe,
#                     and the clock-event mask - what limited the part
#   host              CPU user/kernel split, syscalls, context switches,
#                     memory and disk - the half the GPU counters cannot see
#   slots             per-request prompt depth, cache hits, decoded tokens
#   metrics           cumulative server counters: the EXACT prefill-against-
#                     decode time split, and KV cache occupancy
#   server log        per-request timings and speculative-decoding acceptance,
#                     which no endpoint exposes
param(
    [Parameter(Mandatory=$true)][string]$Model,
    [Parameter(Mandatory=$true)][string]$Tag,
    [int]$Port = 1283,
    [int]$NumTests = -1,
    [string]$EditFormat = "whole",
    [string]$Repo = "E:\AI\measured-inference",
    [string]$ServerBin = "E:\AI\llama.cpp\llama-server.exe"
)

$ErrorActionPreference = "Stop"
$tel = Join-Path $Repo "results\qwen38-27b-blind\data\telemetry"
$logs = Join-Path $Repo "results\qwen38-27b-blind\logs"
New-Item -ItemType Directory -Force -Path $tel, $logs | Out-Null

if (-not (Test-Path $Model)) { throw "model not found: $Model" }

# Refuse to start on top of a live server: it would serve this arm's requests
# from the PREVIOUS arm's weights and every number would be attributed wrong.
$live = Get-Process -Name "llama-server" -ErrorAction SilentlyContinue
if ($live) {
    throw ("llama-server is already running (pid $($live.Id)). Stop it first - " +
           "starting an arm against another arm's weights silently mislabels " +
           "every result.")
}

$srvLog = Join-Path $logs "$Tag-server.log"

# The flags below are the shipped recipe and must match across arms: only the
# model file may differ, or the comparison is not a comparison.
$srvArgs = @(
    "-m", $Model,
    "--alias", "qwen",
    "--host", "0.0.0.0",
    "--port", "$Port",
    "-ngl", "99",
    "-c", "32768",
    "--parallel", "1",
    "-fa", "on",
    "-ctk", "q8_0",
    "-ctv", "q8_0",
    "--jinja",
    "--reasoning", "off",
    "--spec-type", "draft-mtp",
    "--spec-draft-n-max", "4",
    "--spec-draft-p-min", "0.75",
    "--metrics"          # <- absent on the first run; see the header
)

Write-Output "starting server -> $srvLog"
# Redirect BOTH streams to a real file. llama.cpp writes its per-request
# timings and its speculative-decoding acceptance counts to stderr, and those
# are the only place acceptance is reported at all.
$srv = Start-Process -FilePath $ServerBin -ArgumentList $srvArgs `
    -RedirectStandardOutput $srvLog -RedirectStandardError "$srvLog.err" `
    -WindowStyle Hidden -PassThru

# Wait for READY. A server still loading answers 503, and a benchmark started
# against it scores zeros on its first exercises and never says why.
$ready = $false
for ($i = 0; $i -lt 300; $i++) {
    Start-Sleep -Seconds 2
    if ($srv.HasExited) { throw "server exited during load - see $srvLog.err" }
    try {
        $r = Invoke-WebRequest -Uri "http://127.0.0.1:$Port/health" -TimeoutSec 5 -UseBasicParsing
        if ($r.StatusCode -eq 200) { $ready = $true; break }
    } catch { }
}
if (-not $ready) { throw "server never became ready on port $Port" }
Write-Output "server ready (pid $($srv.Id))"

# Confirm --metrics actually took effect rather than assuming the flag worked.
try {
    $m = Invoke-WebRequest -Uri "http://127.0.0.1:$Port/metrics" -TimeoutSec 5 -UseBasicParsing
    if ($m.StatusCode -ne 200) { throw "status $($m.StatusCode)" }
    Write-Output "metrics endpoint live"
} catch {
    throw ("--metrics did not take effect ($_). Stopping: an arm without it " +
           "cannot report its prefill/decode time split, and that cannot be " +
           "recovered after the run.")
}

# Samplers start BEFORE the benchmark so the window covers every exercise.
$py = (Get-Command py -ErrorAction SilentlyContinue)
if (-not $py) { throw "py launcher not found" }

function Start-Collector([string]$name, [string[]]$argv) {
    Start-Process -FilePath "py" -ArgumentList $argv -WorkingDirectory $Repo `
        -WindowStyle Hidden | Out-Null
    Write-Output "  collector: $name"
}

Start-Collector "gpu (dmon + throttle)" @("scripts\power\silicon-telemetry.py", "--tag", $Tag)
Start-Collector "slots (per request)"   @("scripts\power\slots-telemetry.py", "--tag", $Tag, "--port", "$Port")
Start-Collector "metrics (cumulative)"  @("scripts\power\metrics-telemetry.py", "--tag", $Tag, "--port", "$Port")
Start-Process -FilePath "powershell" -ArgumentList @(
    "-NoProfile", "-File", (Join-Path $Repo "scripts\power\host-telemetry.ps1"),
    "-Tag", $Tag) -WindowStyle Hidden | Out-Null
Write-Output "  collector: host"

Start-Sleep -Seconds 4
$missing = @()
foreach ($k in @("dmon", "throttle", "slots", "metrics", "host")) {
    $f = Join-Path $tel "$Tag-$k.csv"
    if (-not (Test-Path $f)) { $missing += $k }
}
if ($missing.Count -gt 0) {
    throw ("these collectors wrote no file: " + ($missing -join ", ") +
           ". Refusing to start the benchmark - a run whose instrumentation " +
           "is already incomplete cannot be fixed afterwards.")
}
Write-Output "all five collectors are writing"

# The benchmark runs in WSL. Attached under setsid, never `docker run -d`:
# measured on this machine, detached completed ONE exercise in 80 minutes
# while attached completed TWO in 40 seconds - with -d nothing drains the
# container's output and the run wedges after the first exercise.
$sh = "scripts/agentic/aider-bench-detached.sh"
$wslRepo = (wsl -e wslpath -a ($Repo -replace '\\', '/'))
Write-Output "launching benchmark: $Tag"
wsl -e bash -lc "cd '$wslRepo' && bash $sh '$Tag' $Port '$EditFormat' all $NumTests"

Write-Output ""
Write-Output "arm running.  server log: $srvLog"
Write-Output "  follow:   wsl -e bash -lc 'tail -f ~/bench/logs/aiderbench-$Tag.log'"
Write-Output "  telemetry: $tel\$Tag-*.csv"
