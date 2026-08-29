# run-ladder.ps1 - manifest-driven, streamed, gated quant-ladder runner.
#
#   powershell -NoProfile -ExecutionPolicy Bypass -File run-ladder.ps1
#              [-Manifest <path>] [-DeadlineMinutes 480] [-NoDetectors] [-Once]
#
# WHAT IT GUARANTEES
#   GPU GATE   - a rung starts only when the other session's runner PID is dead,
#                no llama-* process exists, and nvidia-smi memory.used is under
#                the manifest's cap. Polled every gate.poll_s seconds.
#   FILE GATE  - a rung is measured only when its file exists AND its byte size
#                is unchanged across a recheck window, re-confirmed after the
#                GPU gate opens. This runner never downloads, moves or deletes a
#                weight file: another session owns that directory.
#   RESUMABLE  - a rung whose RESULT (or FAILED) line is already in results.txt
#                is skipped. Kill and restart at will.
#   STREAMED   - rungs are measured in manifest order as they stabilise; the
#                loop re-scans from the top after every completion, so a
#                higher-priority file that lands mid-run goes next.
#   ONE JOB    - exactly one GPU process at a time, always waited on.
#
# Perplexity conditions are the campaign's phase-6 conditions (METHODOLOGY rule
# 6): frozen wikitext-2-raw test corpus, -c 8192, -fa on, 36 x 8,192-token
# chunks, f16 KV, -ngl 99. `-fa on --load-mode mmap` reproduces the campaign's
# no-fa anchor bit-for-bit (6.5956 both ways), so the 6.5956 / 6.8774 anchors
# apply unchanged.
param(
    [string]$Manifest = 'E:\AI\measured-inference\scripts\quant-ladder\ladder-manifest.json',
    [int]$DeadlineMinutes = 480,
    [switch]$NoDetectors,
    [switch]$Once
)
. (Join-Path $PSScriptRoot "..\gpu-lock.ps1")

$ErrorActionPreference = 'Continue'
$here = Split-Path -Parent $MyInvocation.MyCommand.Path
. (Join-Path $here 'ladder-lib.ps1')

$M = Get-Manifest $Manifest
$OUT = [string]$M.outdir
if (-not (Test-Path $OUT)) { New-Item -ItemType Directory -Path $OUT -Force | Out-Null }
$LEDGER = Join-Path $OUT 'results.txt'
if (-not (Test-Path $LEDGER)) {
    # a header line so the PS 5.1 utf8 BOM never lands on a RESULT line
    Set-Content -LiteralPath $LEDGER -Value ('# quant-ladder ledger - opened {0}' -f (Get-Date -Format 's')) -Encoding utf8
}
$HEART = Join-Path $OUT 'heartbeat.txt'
$SCRATCH = 'C:\Users\chink\AppData\Local\Temp\claude\E--AI-aider\e44e5644-c7df-41e1-82f5-a8fa4e8cca1a\scratchpad'
if (-not (Test-Path $SCRATCH)) { New-Item -ItemType Directory -Path $SCRATCH -Force | Out-Null }

$DEADLINE = (Get-Date).AddMinutes($DeadlineMinutes)
$LN2 = [math]::Log(2)
$CORPUS = [string]$M.corpus
$CORPUS_BYTES = [double]$M.corpus_bytes

# The bits-per-weight denominator is MEASURED, not typed. measure-bpw.py reads
# the file's own tensor table out of its header (~11 MiB of a 13 GiB file, no
# GPU, no load) and hands back one JSON line. The arithmetic lives in Python
# rather than here because this runner is PowerShell 5.1 and Windows-only,
# and a correct denominator must not be a Windows-only privilege.
$MEASURE_BPW = Join-Path $here 'measure-bpw.py'
$PY = $null
foreach ($cand in @('python', 'python3', 'py')) {
    if (Get-Command $cand -ErrorAction SilentlyContinue) { $PY = $cand; break }
}
if (-not $PY) {
    Write-Log 'WARNING: no python on PATH - bpw will fall back to the manifest''s declared parameter count and every RESULT line will say params_src=manifest-declared (rule 1: that number is DERIVED, not measured).'
}

Write-Log ('=== quant-ladder runner up. deadline {0}. manifest {1} ===' -f $DEADLINE.ToString('MM-dd HH:mm'), $Manifest)
Write-Log ('corpus {0} ({1:N0} bytes)' -f $CORPUS, $CORPUS_BYTES)
if (-not (Test-Path -LiteralPath $CORPUS)) { Write-Log 'FATAL: frozen corpus missing'; exit 1 }

# --------------------------------------------------------------- one rung ----

function Get-HeaderParams {
    # The file's OWN parameter count, summed over every tensor in its header.
    #
    # This replaces $R.params, a number typed into ladder-manifest.json. That
    # number was 27000000000 for every Qwen rung, and the files do not agree
    # with it - measured 2026-08-29: the IQ4_XS/Q3_K_XL/IQ3_XXS/Q2_K_XL group
    # sums to 27,320,697,856 elements and the IQ2_S/IQ2_XXS/IQ1_M/IQ1_S group
    # to 26,895,998,464. One typed denominator across both therefore inflates
    # the top of the ladder by 1.19% and understates the bottom by 0.39%: a
    # 1.57-point error that does NOT cancel between rungs, which is exactly
    # what a ladder compares. Returns $null on any failure; the caller then
    # falls back and LABELS the line, because rule 1 has three categories -
    # measured, cited, labeled-derived - and no fourth.
    param([string]$ModelPath, [string]$Name)
    if (-not $PY) { return $null }
    if (-not (Test-Path -LiteralPath $MEASURE_BPW)) {
        Write-Log ('  bpw: {0} is missing' -f $MEASURE_BPW); return $null
    }
    $out = Join-Path $SCRATCH ('bpw-{0}.json' -f $Name)
    $errf = Join-Path $SCRATCH ('bpw-{0}.err' -f $Name)
    try {
        $p = Start-Process -FilePath $PY -ArgumentList @($MEASURE_BPW, $ModelPath, '--json') `
            -NoNewWindow -PassThru -RedirectStandardOutput $out -RedirectStandardError $errf
        # PS 5.1: a -PassThru process only exposes ExitCode once its handle has
        # been cached, and reading it before that yields $null - which is why
        # Invoke-Ppl below wraps the same access in a try/catch. Cache it here,
        # and then take the VERDICT from the output rather than the code: what
        # this function owes its caller is a parameter count, and a JSON object
        # carrying a positive one is the only thing that counts as having got it.
        $null = $p.Handle
        if (-not $p.WaitForExit(300000)) {
            Write-Log '  bpw: header read TIMEOUT (300s) - killing'
            try { $p.Kill() } catch {}
            return $null
        }
        $code = -1
        try { $code = $p.ExitCode } catch { $code = -1 }
        $j = $null
        if (Test-Path -LiteralPath $out) {
            $raw = Get-Content -LiteralPath $out -Raw -ErrorAction SilentlyContinue
            if ($raw) { try { $j = $raw | ConvertFrom-Json } catch { $j = $null } }
        }
        if (-not $j -or -not $j.params -or [int64]$j.params -le 0) {
            Write-Log ('  bpw: measure-bpw.py gave no parameter count (exit={0}): {1}' -f $code,
                (Get-Content -LiteralPath $errf -Raw -ErrorAction SilentlyContinue))
            return $null
        }
        return $j
    } catch {
        Write-Log ('  bpw: header read failed: {0}' -f "$_")
        return $null
    }
}

function Invoke-Tokenize {
    # Each model's OWN token count for the corpus - rule 6 needs it for
    # bits-per-byte. Vocab-level work, no GPU. Returns $null on any failure.
    param([string]$ModelPath, [string]$Name)
    $dump = Join-Path $SCRATCH ('tok-{0}.txt' -f $Name)
    $errf = Join-Path $SCRATCH ('tok-{0}.err' -f $Name)
    $a = @('-m', $ModelPath, '-f', $CORPUS, '--show-count', '--ids')
    try {
        $p = Start-Process -FilePath ([string]$M.tokenize.exe) -ArgumentList $a -NoNewWindow -PassThru `
            -RedirectStandardOutput $dump -RedirectStandardError $errf
        if (-not $p.WaitForExit(600000)) {
            Write-Host '  tokenize: TIMEOUT (600s) - killing'
            try { $p.Kill() } catch {}
            return $null
        }
    } catch {
        Write-Host ('  tokenize: launch failed: {0}' -f "$_")
        return $null
    }
    # Read the last 4 KiB by seeking, NOT Get-Content -Tail: --ids emits the whole
    # corpus as ONE ~1.7 MB line, and PS 5.1's -Tail walks a file backwards a
    # character at a time looking for the line break - it spins for minutes on a
    # line that long. (Cost the first launch of this runner ~2 min before it was
    # caught; the seek version returns instantly.)
    $n = $null
    try {
        $fs = [IO.File]::OpenRead($dump)
        $take = [int][math]::Min(4096, $fs.Length)
        [void]$fs.Seek(-$take, [IO.SeekOrigin]::End)
        $buf = New-Object byte[] $take
        [void]$fs.Read($buf, 0, $take)
        $fs.Close()
        $tailTxt = [Text.Encoding]::ASCII.GetString($buf)
        $mm = [regex]::Match($tailTxt, '(?i)total number of tokens:\s*(\d+)')
        if ($mm.Success) { $n = [int64]$mm.Groups[1].Value }
    } catch { Write-Host ('  tokenize: tail read failed: {0}' -f "$_") }
    Remove-Item $dump, $errf -ErrorAction SilentlyContinue
    if ($n) { Write-Host ('  tokenize: {0:N0} tokens' -f $n) } else { Write-Host '  tokenize: no count parsed' }
    return $n
}

function Invoke-Ppl {
    param([string]$ModelPath, [string]$Name, $Chunks)
    $log = Join-Path $OUT ('ppl-{0}.log' -f $Name)
    $olog = Join-Path $OUT ('ppl-{0}.out.log' -f $Name)
    $a = @('-m', $ModelPath, '-f', $CORPUS) + [string[]]$M.ppl.flags
    if ($Chunks) { $a += @('--chunks', "$Chunks") }
    Write-Host ('  ppl: {0} {1}' -f ([string]$M.ppl.exe), ($a -join ' '))
    $sw = [Diagnostics.Stopwatch]::StartNew()
    $code = -1
    try {
        $p = Start-GuardedServer -FilePath ([string]$M.ppl.exe) -ArgumentList $a -NoNewWindow -PassThru `
            -RedirectStandardOutput $olog -RedirectStandardError $log
        if (-not $p.WaitForExit(5400000)) {
            Write-Host '  ppl: TIMEOUT (90 min) - killing'
            try { $p.Kill() } catch {}
            $sw.Stop()
            return [pscustomobject]@{ ok = $false; reason = 'timeout'; wall_s = [math]::Round($sw.Elapsed.TotalSeconds, 1) }
        }
        try { $code = $p.ExitCode } catch { $code = -1 }
    } catch {
        $sw.Stop()
        Write-Host ('  ppl: launch failed: {0}' -f "$_")
        return [pscustomobject]@{ ok = $false; reason = 'launch'; wall_s = [math]::Round($sw.Elapsed.TotalSeconds, 1) }
    }
    $sw.Stop()
    $txt = ''
    foreach ($f in @($log, $olog)) {
        if (Test-Path -LiteralPath $f) { $txt += (Get-Content -Raw -LiteralPath $f -ErrorAction SilentlyContinue) }
    }
    $fin = [regex]::Match($txt, 'Final estimate:\s*PPL\s*=\s*([0-9.]+)\s*\+/-\s*([0-9.]+)')
    $chk = [regex]::Match($txt, 'calculating perplexity over\s+(\d+)\s+chunks,\s*n_ctx=(\d+)')
    if (-not $fin.Success) {
        $why = 'no-final-estimate'
        if ($txt -match '(?i)error loading model|failed to load|invalid magic|tensor .* data is not within the file bounds') { $why = 'model-load-failed (file may still be incomplete)' }
        Write-Host ('  ppl: FAILED exit={0} reason={1}' -f $code, $why)
        $tailTxt = Get-Content -LiteralPath $log -Tail 8 -ErrorAction SilentlyContinue
        foreach ($l in $tailTxt) { Write-Host ('    | ' + $l) }
        return [pscustomobject]@{ ok = $false; reason = $why; wall_s = [math]::Round($sw.Elapsed.TotalSeconds, 1) }
    }
    return [pscustomobject]@{
        ok      = $true
        ppl     = [double]$fin.Groups[1].Value
        err     = [double]$fin.Groups[2].Value
        chunks  = $(if ($chk.Success) { [int]$chk.Groups[1].Value } else { 0 })
        n_ctx   = $(if ($chk.Success) { [int]$chk.Groups[2].Value } else { 0 })
        wall_s  = [math]::Round($sw.Elapsed.TotalSeconds, 1)
        exit    = $code
    }
}

function Invoke-Rung {
    param($R, [int64]$Bytes)
    Write-Log ('--- RUNG {0} ({1}) {2:N3} GiB ---' -f $R.name, $R.role, ($Bytes / 1GB))

    # Denominator first: it is cheap, it needs no GPU, and if it is going to
    # fail this rung's operator should learn that now and not after an hour
    # of perplexity.
    $hp = Get-HeaderParams -ModelPath ([string]$R.path) -Name ([string]$R.name)
    if ($hp) {
        $params = [int64]$hp.params
        $paramSrc = 'gguf-header'
        $bpwTensors = [double]$hp.bpw_from_tensors
        if ([int64]$hp.size_bytes -ne $Bytes) {
            # The file gate stabilised $Bytes; the header read saw something
            # else. That is a file changing underneath the run, and it is a
            # condition, not a footnote (rule 3).
            Write-Log ('  bpw: WARNING file size moved between the gate ({0}) and the header read ({1})' -f $Bytes, $hp.size_bytes)
        }
        Write-Log ('  bpw: params={0} from the file''s own header (manifest declared {1}, {2:N3}% off); tensor-table cross-check {3:N4} bpw' -f `
            $params, [int64]$R.params, (100.0 * ([double]$R.params - $params) / $params), $bpwTensors)
    } else {
        $params = [int64]$R.params
        $paramSrc = 'manifest-declared'
        # 'na', not 0: a zero in a bits-per-weight column is a number, and a
        # number nobody measured is the whole failure this change exists to fix.
        $bpwTensors = 'na'
        Write-Log ('  bpw: FALLBACK to the manifest''s declared {0} - this rung''s bpw is DERIVED, not measured (rule 1), and the ledger says so' -f $params)
    }

    $ntok = Invoke-Tokenize -ModelPath ([string]$R.path) -Name ([string]$R.name)
    $res = Invoke-Ppl -ModelPath ([string]$R.path) -Name ([string]$R.name) -Chunks $R.chunks
    if (-not $res.ok) { return $res }

    $evalTok = [double]$res.chunks * [double]$res.n_ctx
    $tokSrc = 'tokenize'
    if (-not $ntok) { $ntok = [int64]$evalTok; $tokSrc = 'eval' }
    $bpw = ([double]$Bytes * 8.0) / [double]$params
    $bpb = ([math]::Log([double]$res.ppl) * [double]$ntok) / ($LN2 * $CORPUS_BYTES)
    $cmp = 'yes'
    if ($R.PSObject.Properties.Name -contains 'ppl_comparable' -and $R.ppl_comparable -eq $false) { $cmp = 'NO-different-tokenizer' }

    # params= is the denominator actually used; params_src= says which of rule
    # 1's three categories the bpw beside it belongs to; params_declared= keeps
    # the manifest's number so the correction stays auditable after the fact,
    # and bpw_tensors= is the independent second measurement (rule 4). Every
    # one of them is written now because rule 28 says a field not written down
    # during the run cannot be recovered at any price.
    $line = ('RESULT {0} | role={1} | file={2} | bytes={3} | GiB={4:N3} | params={5} | params_src={6} | params_declared={7} | bpw={8:N4} | bpw_tensors={9:N4} | PPL={10:N4} | err={11:N5} | chunks={12} | n_ctx={13} | eval_tokens={14} | tokens={15} | tok_src={16} | bpb={17:N4} | ppl_comparable={18} | wall_s={19} | ts={20}' -f `
        $R.name, $R.role, (Split-Path -Leaf ([string]$R.path)), $Bytes, ($Bytes / 1GB),
        $params, $paramSrc, [int64]$R.params, $bpw, $bpwTensors,
        $res.ppl, $res.err, $res.chunks, $res.n_ctx, [int64]$evalTok, $ntok, $tokSrc, $bpb, $cmp,
        $res.wall_s, (Get-Date -Format 's'))
    Write-Ledger $LEDGER $line
    return $res
}

# ------------------------------------------------------------- gate checks ---

function Test-RigGate {
    param($R, $Res)
    $exp = [double]$R.expected_ppl
    $tol = [double]$R.tolerance_pct
    $rel = 100.0 * [math]::Abs($Res.ppl - $exp) / $exp
    $verdict = $(if ($rel -le $tol) { 'PASS' } else { 'DRIFT' })
    Write-Ledger $LEDGER ('RIGGATE {0} | expected={1:N4} | measured={2:N4} | delta_pct={3:N3} | tol_pct={4} | {5}' -f `
        $R.name, $exp, $Res.ppl, $rel, $tol, $verdict)
    if ($verdict -eq 'DRIFT' -and $R.abort_on_drift) {
        Write-Ledger $LEDGER ('ABORT RIG-DRIFT {0}: measured {1:N4} vs expected {2:N4} ({3:N3}% > {4}%). Campaign halted; nothing else measured.' -f `
            $R.name, $Res.ppl, $exp, $rel, $tol)
        return $false
    }
    if ($R.PSObject.Properties.Name -contains 'pair_with' -and $R.pair_with) {
        $other = Get-LedgerField $LEDGER ([string]$R.pair_with) 'PPL'
        if ($other) {
            $gap = 100.0 * ($Res.ppl - [double]$other) / [double]$other
            $ok = $(if ($gap -ge [double]$R.pair_min_gap_pct) { 'RESOLVED' } else { 'COLLAPSED' })
            Write-Ledger $LEDGER ('RIGPAIR {0} vs {1} | gap_pct={2:N3} | min={3} | {4}' -f `
                $R.name, $R.pair_with, $gap, $R.pair_min_gap_pct, $ok)
            if ($ok -eq 'COLLAPSED') {
                Write-Ledger $LEDGER 'ABORT RIG-RESOLUTION: the two anchors no longer separate; the rig cannot rank quants today.'
                return $false
            }
        }
    }
    return $true
}

function Update-Conditionals {
    # PASS 2 is conditional: an infill rung is enabled only where pass 1 shows
    # the curve steepening across its bracket (relative PPL gap >= factor x the
    # gap of the pair above). Mechanical, logged, and overridable by hand with
    # an enable-<name>.flag file.
    foreach ($R in $M.rungs) {
        if (-not $R.conditional) { continue }
        $flag = Join-Path $OUT ('enable-{0}.flag' -f $R.name)
        if (Test-Path $flag) { continue }
        $c = $R.condition
        $a = Get-LedgerField $LEDGER ([string]$c.between[0]) 'PPL'
        $b = Get-LedgerField $LEDGER ([string]$c.between[1]) 'PPL'
        $x = Get-LedgerField $LEDGER ([string]$c.reference_pair[0]) 'PPL'
        $y = Get-LedgerField $LEDGER ([string]$c.reference_pair[1]) 'PPL'
        if (-not ($a -and $b -and $x -and $y)) { continue }
        $gap = ([double]$b - [double]$a) / [double]$a
        $ref = ([double]$y - [double]$x) / [double]$x
        $ratio = $(if ($ref -gt 0) { $gap / $ref } else { 999 })
        if ($ratio -ge [double]$c.factor) {
            Set-Content -LiteralPath $flag -Value ('auto-enabled {0}: gap({1}->{2})={3:P2} is {4:N2}x gap({5}->{6})={7:P2}' -f `
                (Get-Date -Format 's'), $c.between[0], $c.between[1], $gap, $ratio, $c.reference_pair[0], $c.reference_pair[1], $ref) -Encoding utf8
            Write-Ledger $LEDGER ('PASS2-ENABLE {0} | bracket_gap_pct={1:N3} | ref_gap_pct={2:N3} | ratio={3:N2} | factor={4} | ENABLED' -f `
                $R.name, ($gap * 100), ($ref * 100), $ratio, $c.factor)
        } else {
            Write-Log ('pass2 {0}: not enabled (ratio {1:N2} < {2})' -f $R.name, $ratio, $c.factor)
        }
    }
}

function Test-RungEnabled {
    param($R)
    if ($R.enabled) { return $true }
    if (Test-Path (Join-Path $OUT ('enable-{0}.flag' -f $R.name))) { return $true }
    return $false
}

# ------------------------------------------------------------------- loop ----

$attempts = @{}
$suspect = @{}
$pass = 0

while ($true) {
    $pass++
    if ((Get-Date) -ge $DEADLINE) { Write-Log 'DEADLINE reached - stopping'; break }
    if (Test-LedgerHas $LEDGER 'ABORT ') { Write-Log 'ABORT line present in the ledger - stopping'; break }

    Update-Conditionals

    $gatesDone = $true
    foreach ($R in $M.rungs) {
        if ($R.role -eq 'rig-gate' -and -not (Test-LedgerHas $LEDGER ('RESULT ' + $R.name + ' '))) { $gatesDone = $false }
    }

    $pending = @()
    foreach ($R in ($M.rungs | Sort-Object { [int]$_.order })) {
        if (Test-LedgerHas $LEDGER ('RESULT ' + $R.name + ' ')) { continue }
        if (Test-LedgerHas $LEDGER ('FAILED ' + $R.name + ' ')) { continue }
        if (-not (Test-RungEnabled $R)) { continue }
        if (-not $gatesDone -and $R.role -ne 'rig-gate') { continue }
        $pending += $R
    }

    $stamp = ('{0} pass={1} pending={2} gatesDone={3} vram={4}MiB' -f (Get-Date -Format 's'), $pass, $pending.Count, $gatesDone, (Get-VramUsedMiB))
    Set-Content -LiteralPath $HEART -Value $stamp -Encoding utf8

    if ($pending.Count -eq 0) {
        if ($gatesDone) {
            $left = @($M.rungs | Where-Object { -not (Test-LedgerHas $LEDGER ('RESULT ' + $_.name + ' ')) -and -not (Test-LedgerHas $LEDGER ('FAILED ' + $_.name + ' ')) })
            if ($left.Count -eq 0) { Write-Log 'MANIFEST EXHAUSTED - every rung has a RESULT or FAILED line'; break }
        }
        if ($Once) { Write-Log '-Once: nothing runnable right now'; break }
        Write-Log ('nothing runnable (pass {0}); sleeping {1}s' -f $pass, $M.gate.poll_s)
        Start-Sleep -Seconds ([int]$M.gate.poll_s)
        continue
    }

    $progressed = $false
    foreach ($R in $pending) {
        if ((Get-Date) -ge $DEADLINE) { break }
        Write-Log ('checking {0} (order {1}, {2})' -f $R.name, $R.order, $R.role)
        $sz = Test-FileStable -Path ([string]$R.path) -RecheckSec ([int]$M.file_gate.recheck_s)
        if (-not $sz) { continue }

        $minB = [double]$R.expected_gib * 1GB * [double]$M.file_gate.min_frac_of_expected
        if ($sz -lt $minB) {
            $k = [string]$R.name
            if (-not $suspect.ContainsKey($k)) { $suspect[$k] = 0 }
            $suspect[$k] = $suspect[$k] + 1
            if ($suspect[$k] -lt [int]$M.file_gate.suspect_passes_before_accept) {
                Write-Log ('  {0}: stable but only {1:N3} GiB vs expected {2} GiB - holding ({3} passes)' -f $R.name, ($sz / 1GB), $R.expected_gib, $suspect[$k])
                continue
            }
            Write-Log ('  {0}: SIZE-DEVIATION accepted after {1} stable passes ({2:N3} GiB vs expected {3})' -f $R.name, $suspect[$k], ($sz / 1GB), $R.expected_gib)
            Write-Ledger $LEDGER ('NOTE {0} | size {1:N3} GiB is {2:P1} of the expected {3} GiB - measured anyway after {4} stable rechecks' -f $R.name, ($sz / 1GB), ($sz / (1GB * [double]$R.expected_gib)), $R.expected_gib, $suspect[$k])
        }

        if (-not (Wait-GpuGate -Gate $M.gate -Deadline $DEADLINE)) { break }

        # the GPU wait can be long: re-confirm the file did not change under us
        $sz2 = (Get-Item -LiteralPath ([string]$R.path)).Length
        if ($sz2 -ne $sz) { Write-Log ('  {0}: file changed while waiting for the GPU - skipping this pass' -f $R.name); continue }

        $res = Invoke-Rung -R $R -Bytes $sz
        if (-not $res.ok) {
            $k = [string]$R.name
            if (-not $attempts.ContainsKey($k)) { $attempts[$k] = 0 }
            $attempts[$k] = $attempts[$k] + 1
            Write-Log ('  {0}: attempt {1} failed ({2})' -f $R.name, $attempts[$k], $res.reason)
            if ($attempts[$k] -ge 3) {
                Write-Ledger $LEDGER ('FAILED {0} | reason={1} | attempts={2} | ts={3}' -f $R.name, $res.reason, $attempts[$k], (Get-Date -Format 's'))
            }
            $progressed = $true
            break
        }

        if ($R.role -eq 'rig-gate') {
            if (-not (Test-RigGate -R $R -Res $res)) { Write-Log 'RIG GATE FAILED - halting the campaign'; exit 2 }
        }

        if (-not $NoDetectors) {
            Write-Log ('  running detectors for {0}' -f $R.name)
            & (Join-Path $here 'detectors.ps1') -Manifest $Manifest -Only ([string]$R.name) -SkipGate
        }

        $progressed = $true
        break
    }

    if ($Once) { Write-Log '-Once: done'; break }
    if (-not $progressed) {
        Write-Log ('no rung was runnable this pass; sleeping {0}s' -f $M.gate.poll_s)
        Start-Sleep -Seconds ([int]$M.gate.poll_s)
    }
}

Write-Log 'RUN-LADDER DONE'
