<#
================================================================================
 power-matrix.ps1 - the post-sweep energy measurement matrix for Qwen3.8-27B
                    on the RTX 3090 (Windows, PowerShell 5.1)
================================================================================

 WHAT THIS PRODUCES
   One row per arm: mean W, J/decode-token, J/prompt-token, tokens/kWh,
   EDP (J.s), Wh/answer - gross AND idle-subtracted - for every mechanism the
   framework wants tested: speculation, quantization, KV dtype, token regime,
   depth, batching, and (if the shell is elevated) the GPU power cap.

 INSTRUMENTATION TIER - state this on every published figure
   in-band GPU BOARD power (NVML via nvidia-smi --query-gpu=power.draw).
   INSIDE the number : GPU die, VRAM, VRM losses, board fans.
   NOT in the number : PSU conversion loss, CPU / RAM / drives / chassis / display,
                       datacentre PUE. There is no wall meter on this machine, so
                       PSU + platform overhead is UNMEASURED, not estimated.
   Never call these numbers "system power" or "wall power".

 PROTOCOL (identical for every timed arm - one variable changes per arm)
   1. start llama-server with this arm's flags, wait for /health
   2. ONE discarded probe        <- the clock-ramp rule. A request off an idle
                                    board runs at 900-990 MHz vs 1455 settled;
                                    it reads LOW-watt and fake-good J/token.
   3. cooldown (20 s; 30 s for the depth arms - the m2b/m2d cooled protocol)
   4. N=3 timed probes, 5 s apart, temp 0 / top_k 1, ~700 answer tokens
   5. stop the server, integrate the power log over each request's own
      prefill / decode windows (attribute-power.py --drop-first drops step 2)
   Prompt caching stays OFF (capture-request.ps1's default): a cached prefill
   costs almost no energy and would destroy J/prompt-token on a repeated prompt.
   The cost of that honesty is that the depth arms re-prefill every probe - which
   is exactly why F3 is budgeted at ~9 minutes.

 RESUMABLE
   Every arm appends exactly one "RESULT <id> ..." or "SKIPPED <id> ..." line to
   power-matrix-log.txt. Re-running skips any arm that already has one. A crashed
   or failed arm writes "FAILED <id> ..." which does NOT count as done, so it is
   retried. Force a re-run of specific arms with -Redo B2-spec-mtp-n4-p075,B3-...
   Run a subset with -Only. Preview without touching the GPU with -Plan.

 DETACHABLE
   -Detach relaunches this script hidden, writes power-matrix.pid, and returns
   immediately. The detached run transcripts to console-<stamp>.log and appends
   to the same result log, so it is still resumable and still inspectable live.

 SAFETY
   * Refuses to start while ANY llama-server is already running (that is the
     rule-21 sweep or someone else's server) unless -Force.
   * Only ever kills llama-server processes that started AFTER this script did.
   * Starts its OWN power logger into power-matrix-<stamp>.csv via
     sample-power.ps1; never touches the campaign's running rule21 logger.
   * If it changes the GPU power limit it restores the card's default limit in a
     finally block, and it also restores a stale non-default limit found at start.

 USAGE
   powershell -NoProfile -ExecutionPolicy Bypass -File power-matrix.ps1 -Plan
   powershell -NoProfile -ExecutionPolicy Bypass -File power-matrix.ps1 -Detach
   powershell -NoProfile -ExecutionPolicy Bypass -File power-matrix.ps1 -Only F1-depth-1k5,F2-depth-28k
   See power-matrix-README.md in this directory for the runbook.
================================================================================
#>
[CmdletBinding()]
param(
    # comma-separated arm ids; empty = the whole matrix
    [string]$Only = '',
    # comma-separated arm ids to re-run even though the log already has them
    [string]$Redo = '',
    # print the plan + estimated wall clock and exit; touches nothing
    [switch]$Plan,
    # relaunch hidden and return immediately
    [switch]$Detach,
    # bypass the "another llama-server is running" guard (dangerous mid-sweep)
    [switch]$Force,
    [string]$Python = 'python',
    # 1234 is held by LM Studio on this box; the campaign measures on 1235
    [int]$Port = 1235,
    [int]$NPredict = 700,
    [int]$Repeat = 3,
    [int]$CooldownSec = 20,
    [int]$DepthCooldownSec = 30,
    [int]$SettleSec = 5,
    [int]$InterArmSec = 15,
    # loaded-idle reference measured on this box: 30.7-31.1 W
    [double]$IdleW = 31.0,
    [int]$IdleWindowSec = 60,
    [string]$LoadMode = 'mmap',
    # skip section H entirely (e.g. when you know the shell is not elevated)
    [switch]$SkipPowerLimit
)

$ErrorActionPreference = 'Continue'
Set-StrictMode -Off

# ------------------------------------------------------------------ paths
$script:ROOT     = 'E:\AI\measured-inference'
$script:WORK     = Join-Path $script:ROOT 'results\qwen38-27b-blind\work'
$script:PDIR     = Join-Path $script:ROOT 'results\qwen38-27b-blind\data\power'
$script:MDIR     = Join-Path $script:ROOT 'results\qwen38-27b-blind\data\power-matrix'
$script:EVDIR    = Join-Path $script:MDIR 'events'
$script:PROMPTS  = Join-Path $script:MDIR 'prompts'
$script:SRVDIR   = Join-Path $script:MDIR 'srv'
$script:LOG      = Join-Path $script:MDIR 'power-matrix-log.txt'
$script:ARMJSONL = Join-Path $script:MDIR 'power-matrix-arms.jsonl'
$script:PIDFILE  = Join-Path $script:MDIR 'power-matrix.pid'

$script:SAMPLE  = Join-Path $script:ROOT 'scripts\power\sample-power.ps1'
$script:CAPTURE = Join-Path $script:ROOT 'scripts\power\capture-request.ps1'
$script:ATTRIB  = Join-Path $script:ROOT 'scripts\power\attribute-power.py'
$script:EXE     = 'E:\AI\llama.cpp\llama-server.exe'

$script:LMS     = 'C:\Users\chink\.lmstudio\models'
$script:M_IQ4XS = Join-Path $script:LMS 'unsloth\Qwen3.8-27B-GGUF\Qwen3.8-27B-UD-IQ4_XS.gguf'
$script:M_Q4KM  = Join-Path $script:LMS 'lmstudio-community\Qwen3.8-27B-GGUF\Qwen3.8-27B-Q4_K_M.gguf'
$script:M_NVFP4 = Join-Path $script:LMS 'esatapedico\Qwen3.8-27B-NVFP4-MTP-GGUF\Qwen3.8-27B-NVFP4-MTP-HIGH.gguf'

$script:ALIAS = 'qwen/qwen3.8-27b'
$script:BASE  = "http://127.0.0.1:$Port"
$script:PY    = $Python

# the campaign's canonical short code probe (lib.ps1 $CODE_PROBE, verbatim)
$script:CODE_PROBE = 'Write a single self-contained JavaScript file implementing a red-black tree class with insert, delete, search and an in-order iterator. Code only, no explanation.'

$script:T_BEGIN     = Get-Date
$script:STAMP       = (Get-Date).ToString('yyyyMMdd-HHmmss')
$script:PL_DEFAULT  = $null
$script:PL_OK       = $false
$script:PL_MSG      = ''
$script:PL_CHANGED  = $false
$script:POWERCSV    = $null
$script:SRVPROC     = $null

# ------------------------------------------------------------- tiny helpers
function Inv {
    param($v, [int]$d = -1)
    if ($null -eq $v) { return 'n/a' }
    try { $x = [double]$v } catch { return 'n/a' }
    if ([double]::IsNaN($x) -or [double]::IsInfinity($x)) { return 'n/a' }
    if ($d -ge 0) { $x = [math]::Round($x, $d) }
    return $x.ToString([System.Globalization.CultureInfo]::InvariantCulture)
}

function Ensure-Dir {
    param([string]$Path)
    if (-not (Test-Path -LiteralPath $Path)) { New-Item -ItemType Directory -Path $Path -Force | Out-Null }
}

function Add-LogLine {
    # .NET no-BOM append: PS 5.1's Add-Content -Encoding utf8 writes a BOM, which
    # would put a stray char on line 1 and break the resume regex.
    param([string]$Line)
    $enc = New-Object System.Text.UTF8Encoding($false)
    [System.IO.File]::AppendAllText($script:LOG, $Line + [Environment]::NewLine, $enc)
}

function Write-Log {
    param([string]$Line)
    Write-Host $Line
    Add-LogLine $Line
}

function Get-LogLines {
    if (-not (Test-Path -LiteralPath $script:LOG)) { return @() }
    return @(Get-Content -LiteralPath $script:LOG -ErrorAction SilentlyContinue)
}

function Test-ArmDone {
    param([string]$Id)
    $rx = '^(RESULT|SKIPPED) ' + [regex]::Escape($Id) + ' '
    foreach ($l in (Get-LogLines)) { if ($l -match $rx) { return $true } }
    return $false
}

function Get-Gpu {
    $l = ''
    try {
        $l = ((nvidia-smi --query-gpu=temperature.gpu,clocks.sm,power.draw,utilization.gpu --format=csv,noheader,nounits) | Select-Object -First 1)
        if ($null -ne $l) { $l = ([string]$l).Trim() }
    } catch { $l = '' }
    return ($l -replace '\s*,\s*', '/')
}

function Get-Vram {
    # Board total from NVML; llama-server's own dedicated/shared split from the
    # Windows GPU perf counters (nvidia-smi is per-process blind on Windows).
    # shr > 0 is the SPILL signature - the model is living partly in system RAM.
    $tot = 0
    try { $tot = [int](((nvidia-smi --query-gpu=memory.used --format=csv,noheader,nounits) | Select-Object -First 1).Trim()) } catch { $tot = 0 }
    $ded = 0; $shr = 0
    $p = Get-Process llama-server -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($p) {
        try {
            $c = Get-Counter '\GPU Process Memory(*)\Dedicated Usage' -ErrorAction Stop
            foreach ($s in $c.CounterSamples) { if ($s.InstanceName -match "pid_$($p.Id)_") { $ded += $s.CookedValue } }
            $c2 = Get-Counter '\GPU Process Memory(*)\Shared Usage' -ErrorAction Stop
            foreach ($s in $c2.CounterSamples) { if ($s.InstanceName -match "pid_$($p.Id)_") { $shr += $s.CookedValue } }
        } catch { }
    }
    return [pscustomobject]@{
        board_mib   = $tot
        srv_ded_mib = [math]::Round($ded / 1MB, 0)
        srv_shr_mib = [math]::Round($shr / 1MB, 0)
    }
}

function Get-LlamaProcs {
    $out = @()
    foreach ($p in @(Get-Process llama-server -ErrorAction SilentlyContinue)) {
        $st = $null
        try { $st = $p.StartTime } catch { $st = $null }
        $out += [pscustomobject]@{ Id = $p.Id; Started = $st }
    }
    return $out
}

# ------------------------------------------------------------------ prompts
function Get-Filler {
    # byte-identical to followup-m2b/m2d Get-Filler - the depths and the wording
    # match the campaign's measured ladder, so t/s here cross-checks against
    # m2d (86.3 / 80.2 / 64.8 t/s at 1.5k / 28k / 91k, answer tokens, n4/p0.75).
    param([int]$n, [int]$seed)
    $ls = New-Object System.Collections.Generic.List[string]
    for ($i = 1; $i -le $n; $i++) {
        $frag = [Convert]::ToString(((($i + $seed) * 48271) % 1048573), 16)
        $ls.Add('Note ' + $i + ': subsystem alpha-' + ((($i + $seed) * 7) % 97) + ' reported latency ' + ((17 * $i) % 993) + ' ms on shard ' + ($i % 13) + ', retry budget ' + ((3 * $i) % 29) + ', digest fragment ' + $frag + ', remark: the threshold was crossed only when the moving median over window ' + ((5 * $i) % 47) + ' exceeded the rolling baseline by ' + ((11 * $i) % 83) + ' percent during the ' + ((13 * $i) % 31) + ' minute observation interval.')
    }
    return [string]::Join("`n", $ls)
}

function New-PromptFiles {
    Ensure-Dir $script:PROMPTS
    $map = @{}
    $specs = @(
        @{ key = 'std';  notes = 20;   seed = 11 },   # ~1.5k tokens
        @{ key = 'd28k'; notes = 400;  seed = 12 },   # ~28k tokens
        @{ key = 'd91k'; notes = 1275; seed = 13 }    # ~91k tokens
    )
    foreach ($s in $specs) {
        $p = Join-Path $script:PROMPTS ('prompt-' + $s.key + '.txt')
        if (-not (Test-Path -LiteralPath $p)) {
            $txt = "Session id m2d-ladder run $($s.seed).`n" +
                   'Read these operations notes, then do the task at the end.' + "`n" +
                   (Get-Filler $s.notes $s.seed) + "`nTASK: " + $script:CODE_PROBE
            [System.IO.File]::WriteAllText($p, $txt, (New-Object System.Text.UTF8Encoding($false)))
        }
        $map[$s.key] = $p
    }
    return $map
}

# ------------------------------------------------------------------- server
function Stop-Server {
    $procs = Get-LlamaProcs
    $killed = 0
    foreach ($p in $procs) {
        $mine = $false
        if ($null -eq $p.Started) { $mine = $false } elseif ($p.Started -ge $script:T_BEGIN) { $mine = $true }
        if ($mine) {
            try { Stop-Process -Id $p.Id -Force -Confirm:$false; $killed++ } catch { }
        } else {
            Write-Host "      WARN foreign llama-server pid=$($p.Id) started $($p.Started) left running (not ours)"
        }
    }
    $script:SRVPROC = $null
    if ($killed -gt 0) { Start-Sleep -Seconds 3 }
}

function Build-SrvArgs {
    param($a)
    $x = @('-c', "$($a.ctx)", '-ngl', '99', '--parallel', "$($a.parallel)",
           '--load-mode', $script:LoadModeVal, '-ctk', $a.ctk, '-ctv', $a.ctv)
    if ($a.spec -eq 'none')     { $x += @('--spec-type', 'none') }
    elseif ($a.spec -eq 'n4')   { $x += @('--spec-type', 'draft-mtp', '--spec-draft-n-max', '4',  '--spec-draft-p-min', '0.75') }
    elseif ($a.spec -eq 'n10')  { $x += @('--spec-type', 'draft-mtp', '--spec-draft-n-max', '10', '--spec-draft-p-min', '0.5') }
    else { throw "unknown spec: $($a.spec)" }
    if ($a.think) { $x += @('--reasoning-preserve') }
    else          { $x += @('--chat-template-kwargs', '{\"enable_thinking\":false}') }
    return $x
}

function Start-Server {
    param([string]$Model, [string[]]$Extra, [string]$Tag, [int]$TimeoutSec = 900)
    Stop-Server
    Ensure-Dir $script:SRVDIR
    $errLog = Join-Path $script:SRVDIR "srv-$Tag.err.log"
    $outLog = Join-Path $script:SRVDIR "srv-$Tag.out.log"
    Remove-Item $errLog, $outLog -ErrorAction SilentlyContinue
    if (-not (Test-Path -LiteralPath $Model)) {
        Write-Host "      model not found: $Model"
        return $null
    }
    # NOTE: --api-key is deliberately omitted (capture-request.ps1 sends no
    # Authorization header) and the serve-qwen.bat sampler defaults are omitted
    # because every request pins temperature 0 / top_k 1. Neither affects energy.
    $a = @('-m', $Model, '--alias', $script:ALIAS, '--host', '127.0.0.1',
           '--port', "$($script:PortVal)", '--jinja') + $Extra
    Write-Host ("      llama-server " + ($a -join ' '))
    $sw = [Diagnostics.Stopwatch]::StartNew()
    $proc = Start-Process -FilePath $script:EXE -ArgumentList $a -WindowStyle Hidden `
        -RedirectStandardError $errLog -RedirectStandardOutput $outLog -PassThru
    $ok = $false
    for ($i = 0; $i -lt ($TimeoutSec / 2); $i++) {
        Start-Sleep -Seconds 2
        try {
            $h = Invoke-RestMethod "$($script:BASE)/health" -TimeoutSec 3
            if ($h.status -eq 'ok') { $ok = $true; break }
        } catch { }
        if ($proc.HasExited) { break }
    }
    $sw.Stop()
    if (-not $ok) {
        Write-Host "      SERVER FAILED (exited=$($proc.HasExited)) after $([math]::Round($sw.Elapsed.TotalSeconds,1))s"
        if (Test-Path -LiteralPath $errLog) {
            Get-Content -LiteralPath $errLog -Tail 12 | ForEach-Object { Write-Host "        | $_" }
        }
        Stop-Server
        return $null
    }
    $script:SRVPROC = $proc
    Write-Host "      healthy in $([math]::Round($sw.Elapsed.TotalSeconds,1))s"
    return [pscustomobject]@{ proc = $proc; err = $errLog; out = $outLog; load_s = [math]::Round($sw.Elapsed.TotalSeconds, 1) }
}

# ------------------------------------------------------------------ capture
function Invoke-Capture {
    param(
        [string]$Label, [string]$PromptFile, [string]$Events,
        [int]$Reps = 1, [int]$Settle = 0, [int]$N = 0
    )
    if ($N -le 0) { $N = $script:NPredictVal }
    $out = & $script:CAPTURE -Label $Label -PromptFile $PromptFile -Events $Events `
        -BaseUrl $script:BASE -OutDir $script:EVDIR -NPredict $N -Temp 0 -TopK 1 `
        -Chat -Model $script:ALIAS -Repeat $Reps -SettleSeconds $Settle 2>&1
    foreach ($l in $out) { Write-Host ("      | " + $l) }
}

function Read-Events {
    param([string]$Path)
    $rows = @()
    if (-not (Test-Path -LiteralPath $Path)) { return $rows }
    foreach ($l in (Get-Content -LiteralPath $Path -ErrorAction SilentlyContinue)) {
        $t = ([string]$l).Trim()
        if ($t -eq '') { continue }
        try { $rows += ($t | ConvertFrom-Json) } catch { }
    }
    return $rows
}

# -------------------------------------------------------------- attribution
function Get-PowerCsvs {
    $csvs = @()
    foreach ($f in @(Get-ChildItem -LiteralPath $script:PDIR -Filter 'power-matrix-*.csv' -ErrorAction SilentlyContinue | Sort-Object Name)) {
        if ($f.Length -gt 0) { $csvs += $f.FullName }
    }
    return $csvs
}

function Invoke-Attribute {
    param(
        [string]$Label, [string[]]$EventFiles = @(),
        [string]$WinT0 = '', [string]$WinT1 = '', [string]$WinTokens = '',
        [string]$JsonOut, [switch]$DropFirst
    )
    # Let the 500 ms logger flush past the end of the window before integrating,
    # otherwise the last sample can predate t_end and the arm reports cov < 100 %.
    Start-Sleep -Seconds 3
    $csvs = Get-PowerCsvs
    if ($csvs.Count -eq 0) { Write-Host '      no power CSV found - cannot attribute'; return $null }
    $pa = @($script:ATTRIB)
    foreach ($p in $csvs)       { $pa += @('--power', $p) }
    foreach ($e in $EventFiles) { $pa += @('--events', $e) }
    if ($WinT0 -ne '')     { $pa += @('--window', $WinT0, $WinT1, $Label) }
    if ($WinTokens -ne '') { $pa += @('--label-tokens', ($Label + '=' + $WinTokens)) }
    $pa += @('--idle-w', (Inv $script:IdleWVal), '--max-gap', '2.0', '--min-coverage', '0.9',
             '--json', $JsonOut, '--quiet')
    if ($DropFirst) { $pa += '--drop-first' }
    Remove-Item -LiteralPath $JsonOut -ErrorAction SilentlyContinue
    $out = & $script:PY @pa 2>&1
    foreach ($l in $out) { Write-Host ("      # " + $l) }
    if (-not (Test-Path -LiteralPath $JsonOut)) { return $null }
    $j = $null
    try { $j = Get-Content -LiteralPath $JsonOut -Raw -Encoding UTF8 | ConvertFrom-Json } catch { return $null }
    return ($j.arms | Where-Object { $_.label -eq $Label } | Select-Object -First 1)
}

function Write-ArmResult {
    param([string]$Id, $R, [string]$Mode, [string]$Cfg, $Vram, [string]$Extra = '')
    if ($null -eq $R) { Write-Log "FAILED $Id reason=attribution-empty cfg=`"$Cfg`""; return }
    $cov = 0.0
    if ($null -ne $R.coverage) { $cov = [double]$R.coverage * 100.0 }
    $vb = 'n/a'; $vs = 'n/a'
    if ($null -ne $Vram) { $vb = "$($Vram.board_mib)"; $vs = "$($Vram.srv_shr_mib)" }
    $line = "RESULT $Id mode=$Mode n=$($R.n_requests)" +
            " mean_W=$(Inv $R.mean_w 1) peak_W=$(Inv $R.peak_w 1)" +
            " J_dec_tok=$(Inv $R.j_per_decode_token 3) J_dec_tok_net=$(Inv $R.j_per_decode_token_net 3)" +
            " J_prompt_tok=$(Inv $R.j_per_prompt_token 4)" +
            " tok_kWh=$(Inv $R.tokens_per_kwh 0) tok_kWh_net=$(Inv $R.tokens_per_kwh_net 0)" +
            " EDP_Js=$(Inv $R.edp_js 0) dec_tps=$(Inv $R.decode_tps 2)" +
            " Wh_ans=$(Inv $R.wh_per_answer_gross 4) Wh_ans_net=$(Inv $R.wh_per_answer_net 4)" +
            " J_gross=$(Inv $R.j_gross 1) pre_s=$(Inv $R.prefill_s 2) dec_s=$(Inv $R.decode_s 2)" +
            " prompt_n=$($R.prompt_n) pred_n=$($R.predicted_n) cov_pct=$(Inv $cov 1)" +
            " vram_board=$vb vram_shr=$vs"
    if ($Extra -ne '') { $line += " $Extra" }
    $line += " cfg=`"$Cfg`""
    Write-Log $line
    if ($cov -lt 90.0) {
        Write-Log "  WARN $Id coverage $(Inv $cov 1)% - the power log has holes inside this arm's windows; mean W and J are understated"
    }
    if ($null -ne $R.mean_w) {
        if ([double]$R.mean_w -lt 250.0 -and $Mode -eq 'phase-split') {
            Write-Log "  WARN $Id mean $(Inv $R.mean_w 1) W is far below the ~344 W sustained-decode reference - check clocks.sm in the CSV for a ramping board"
        }
    }
    $rec = [ordered]@{ id = $Id; mode = $Mode; cfg = $Cfg; t = (Get-Date).ToString('s'); arm = $R }
    $enc = New-Object System.Text.UTF8Encoding($false)
    [System.IO.File]::AppendAllText($script:ARMJSONL, ($rec | ConvertTo-Json -Depth 8 -Compress) + [Environment]::NewLine, $enc)
}

# ------------------------------------------------------------- power limit
function Get-PowerLimits {
    $def = $null; $cur = $null
    try { $def = [double]((nvidia-smi --query-gpu=power.default_limit --format=csv,noheader,nounits) | Select-Object -First 1) } catch { }
    try { $cur = [double]((nvidia-smi --query-gpu=power.limit         --format=csv,noheader,nounits) | Select-Object -First 1) } catch { }
    return [pscustomobject]@{ default_w = $def; current_w = $cur }
}

function Set-PowerLimit {
    param([int]$Watts)
    $o = ''
    try { $o = (& nvidia-smi -pl $Watts 2>&1 | Out-String).Trim() } catch { $o = "$($_.Exception.Message)" }
    $code = $LASTEXITCODE
    $now = (Get-PowerLimits).current_w
    $ok = ($code -eq 0)
    if ($null -ne $now) { if ([math]::Abs([double]$now - $Watts) -gt 1.0) { $ok = $false } }
    return [pscustomobject]@{ ok = $ok; exit = $code; msg = ($o -replace '\s+', ' '); now_w = $now }
}

function Test-Elevated {
    try {
        $id = [Security.Principal.WindowsIdentity]::GetCurrent()
        $pr = New-Object Security.Principal.WindowsPrincipal($id)
        return $pr.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
    } catch { return $false }
}

# ================================================================= arm table
# est_s includes this arm's server load, discarded probe, cooldown, timed
# probes and the inter-arm settle. Derived from the campaign's measured t/s:
# no-spec 43, n4/p0.75 83-86, n10/p0.5 94, Q4_K_M no-spec 40, NVFP4 no-spec ~28,
# thinking-on ~50, depth 86/80/65, prefill ~865 tok/s.
function Get-Arms {
    param([hashtable]$P)
    $A = @()

    $A += @{ id='A1-idle-noserver'; kind='idle'; est=100
             desc='board idle, NO server, 60 s'
             cfg='no server; NVML board idle' }

    $A += @{ id='A2-idle-loaded'; kind='loaded-idle'; est=160
             desc='loaded idle: server up + model resident, 60 s, no requests'
             model=$script:M_IQ4XS; ctx=32768; ctk='q8_0'; ctv='q8_0'; spec='none'; think=$false; parallel=1
             cfg='IQ4_XS c32768 spec=none kv=q8_0 par=1 think=off; idle 60 s' }

    # ---- B. speculation ---------------------------------------------------
    $A += @{ id='B1-spec-none'; kind='req'; est=150; prompt=$P['std']
             desc='IQ4_XS c32768, --spec-type none'
             model=$script:M_IQ4XS; ctx=32768; ctk='q8_0'; ctv='q8_0'; spec='none'; think=$false; parallel=1
             cfg='IQ4_XS c32768 spec=none kv=q8_0 par=1 think=off prompt=1.5k' }
    $A += @{ id='B2-spec-mtp-n4-p075'; kind='req'; est=120; prompt=$P['std']
             desc='IQ4_XS c32768, MTP n-max 4 / p-min 0.75'
             model=$script:M_IQ4XS; ctx=32768; ctk='q8_0'; ctv='q8_0'; spec='n4'; think=$false; parallel=1
             cfg='IQ4_XS c32768 spec=n4/p0.75 kv=q8_0 par=1 think=off prompt=1.5k' }
    $A += @{ id='B3-spec-mtp-n10-p05'; kind='req'; est=115; prompt=$P['std']
             desc='IQ4_XS c32768, MTP n-max 10 / p-min 0.5'
             model=$script:M_IQ4XS; ctx=32768; ctk='q8_0'; ctv='q8_0'; spec='n10'; think=$false; parallel=1
             cfg='IQ4_XS c32768 spec=n10/p0.5 kv=q8_0 par=1 think=off prompt=1.5k' }

    # ---- C. quantization (no spec, same probe) ----------------------------
    # C1 repeats B1's configuration on purpose: an independent re-measure of an
    # identical arm is this matrix's run-to-run noise floor.
    $A += @{ id='C1-quant-iq4xs'; kind='req'; est=150; prompt=$P['std']
             desc='UD-IQ4_XS 13.3 GiB, no spec  (= B1 config: noise check)'
             model=$script:M_IQ4XS; ctx=32768; ctk='q8_0'; ctv='q8_0'; spec='none'; think=$false; parallel=1
             cfg='IQ4_XS c32768 spec=none kv=q8_0 par=1 think=off prompt=1.5k' }
    $A += @{ id='C2-quant-q4km'; kind='req'; est=175; prompt=$P['std']
             desc='Q4_K_M 15.4 GiB, no spec'
             model=$script:M_Q4KM; ctx=32768; ctk='q8_0'; ctv='q8_0'; spec='none'; think=$false; parallel=1
             cfg='Q4_K_M c32768 spec=none kv=q8_0 par=1 think=off prompt=1.5k' }
    $A += @{ id='C3-quant-nvfp4-high'; kind='req'; est=215; prompt=$P['std']
             desc='NVFP4-MTP-HIGH 17.6 GB, no spec (dequant fallback on sm_86)'
             model=$script:M_NVFP4; ctx=32768; ctk='q8_0'; ctv='q8_0'; spec='none'; think=$false; parallel=1
             cfg='NVFP4-HIGH c32768 spec=none kv=q8_0 par=1 think=off prompt=1.5k' }

    # ---- D. KV cache dtype -------------------------------------------------
    $A += @{ id='D1-kv-f16'; kind='req'; est=155; prompt=$P['std']
             desc='IQ4_XS no spec, KV f16'
             model=$script:M_IQ4XS; ctx=32768; ctk='f16'; ctv='f16'; spec='none'; think=$false; parallel=1
             cfg='IQ4_XS c32768 spec=none kv=f16 par=1 think=off prompt=1.5k' }
    $A += @{ id='D2-kv-q8'; kind='req'; est=150; prompt=$P['std']
             desc='IQ4_XS no spec, KV q8_0  (= B1/C1 config: 3rd noise point)'
             model=$script:M_IQ4XS; ctx=32768; ctk='q8_0'; ctv='q8_0'; spec='none'; think=$false; parallel=1
             cfg='IQ4_XS c32768 spec=none kv=q8_0 par=1 think=off prompt=1.5k' }

    # ---- E. token regime ---------------------------------------------------
    $A += @{ id='E1-think-on'; kind='req'; est=175; prompt=$P['std']
             desc='IQ4_XS n4/p0.75, thinking ON (--reasoning-preserve, server default effort)'
             model=$script:M_IQ4XS; ctx=32768; ctk='q8_0'; ctv='q8_0'; spec='n4'; think=$true; parallel=1
             cfg='IQ4_XS c32768 spec=n4/p0.75 kv=q8_0 par=1 think=ON prompt=1.5k' }
    $A += @{ id='E2-think-off'; kind='req'; est=120; prompt=$P['std']
             desc='IQ4_XS n4/p0.75, thinking OFF (= B2 config: 2nd noise point)'
             model=$script:M_IQ4XS; ctx=32768; ctk='q8_0'; ctv='q8_0'; spec='n4'; think=$false; parallel=1
             cfg='IQ4_XS c32768 spec=n4/p0.75 kv=q8_0 par=1 think=off prompt=1.5k' }

    # ---- F. depth (cooled protocol, cache OFF so every probe re-prefills) ---
    $A += @{ id='F1-depth-1k5'; kind='req'; est=140; prompt=$P['std']; deep=$true
             desc='IQ4_XS n4/p0.75 c131072, ~1.5k fill'
             model=$script:M_IQ4XS; ctx=131072; ctk='q8_0'; ctv='q8_0'; spec='n4'; think=$false; parallel=1
             cfg='IQ4_XS c131072 spec=n4/p0.75 kv=q8_0 par=1 think=off prompt=~1.5k' }
    $A += @{ id='F2-depth-28k'; kind='req'; est=255; prompt=$P['d28k']; deep=$true
             desc='IQ4_XS n4/p0.75 c131072, ~28k fill'
             model=$script:M_IQ4XS; ctx=131072; ctk='q8_0'; ctv='q8_0'; spec='n4'; think=$false; parallel=1
             cfg='IQ4_XS c131072 spec=n4/p0.75 kv=q8_0 par=1 think=off prompt=~28k' }
    $A += @{ id='F3-depth-91k'; kind='req'; est=555; prompt=$P['d91k']; deep=$true
             desc='IQ4_XS n4/p0.75 c131072, ~91k fill (4 full prefills: cache is OFF)'
             model=$script:M_IQ4XS; ctx=131072; ctk='q8_0'; ctv='q8_0'; spec='n4'; think=$false; parallel=1
             cfg='IQ4_XS c131072 spec=n4/p0.75 kv=q8_0 par=1 think=off prompt=~91k' }

    # ---- G. batching -------------------------------------------------------
    # Coarse windows on purpose: two OVERLAPPING requests cannot be summed
    # per-request without double-counting the same joules. One window over the
    # whole burst / pair, divided by the tokens both answers produced, is the
    # honest aggregate. G1 is the matched --parallel 1 comparator.
    $A += @{ id='G1-parallel-1'; kind='coarse-seq'; est=120; prompt=$P['std']
             desc='IQ4_XS no spec, --parallel 1, 2 requests back to back (aggregate)'
             model=$script:M_IQ4XS; ctx=32768; ctk='q8_0'; ctv='q8_0'; spec='none'; think=$false; parallel=1
             cfg='IQ4_XS c32768 spec=none kv=q8_0 par=1 think=off prompt=1.5k; 2 seq requests, coarse window' }
    $A += @{ id='G2-parallel-2'; kind='coarse-par'; est=120; prompt=$P['std']
             desc='IQ4_XS no spec, --parallel 2, 2 CONCURRENT requests (aggregate)'
             model=$script:M_IQ4XS; ctx=32768; ctk='q8_0'; ctv='q8_0'; spec='none'; think=$false; parallel=2
             cfg='IQ4_XS c32768 spec=none kv=q8_0 par=2 think=off prompt=1.5k; 2 concurrent requests, coarse window' }

    # ---- H. GPU power cap (needs an elevated shell) ------------------------
    $A += @{ id='H1-plimit-250'; kind='plimit'; est=150; plimit=250; prompt=$P['std']
             desc='section B winner config at nvidia-smi -pl 250'
             cfg='B-winner config, board power cap 250 W' }
    $A += @{ id='H2-plimit-300'; kind='plimit'; est=150; plimit=300; prompt=$P['std']
             desc='section B winner config at nvidia-smi -pl 300'
             cfg='B-winner config, board power cap 300 W' }

    return $A
}

function Get-ArmById {
    param([string]$Id)
    foreach ($a in $script:ARMS) { if ($a.id -eq $Id) { return $a } }
    return $null
}

function Get-BestSpecArm {
    # The B arm with the lowest J/decode-token, read back out of the log so it
    # survives a resume in a fresh process.
    $best = $null; $bestV = [double]::MaxValue
    foreach ($l in (Get-LogLines)) {
        $m = [regex]::Match($l, '^RESULT (B[0-9][^\s]*) .*\sJ_dec_tok=([0-9]+(?:\.[0-9]+)?)\s')
        if ($m.Success) {
            $v = [double]$m.Groups[2].Value
            if ($v -lt $bestV) { $bestV = $v; $best = $m.Groups[1].Value }
        }
    }
    if ($null -eq $best) { return $null }
    return [pscustomobject]@{ id = $best; j = $bestV }
}

# =================================================================== runners
function Invoke-ReqArm {
    param($a, [string]$IdOverride = '', [string]$CfgSuffix = '')
    $id = $a.id
    if ($IdOverride -ne '') { $id = $IdOverride }
    $ev = Join-Path $script:EVDIR ("events-$id.jsonl")
    Remove-Item -LiteralPath $ev -ErrorAction SilentlyContinue   # never inherit a stale retry
    $srv = Start-Server -Model $a.model -Extra (Build-SrvArgs $a) -Tag $id
    if ($null -eq $srv) { Write-Log "FAILED $id reason=server-load"; return }
    $v0 = Get-Vram
    Write-Log ("  LOAD $id load_s=$($srv.load_s) vram_board=$($v0.board_mib) vram_ded=$($v0.srv_ded_mib) vram_shr=$($v0.srv_shr_mib) gpu=$(Get-Gpu)")
    if ($v0.srv_shr_mib -gt 0) { Write-Log "  WARN $id SPILL shared=$($v0.srv_shr_mib) MiB - this arm is partly in system RAM" }

    Write-Host '      discarded probe (clock ramp / prefill) ...'
    Invoke-Capture -Label $id -PromptFile $a.prompt -Events $ev -Reps 1
    $cool = $script:CooldownVal
    if ($a.deep) { $cool = $script:DepthCooldownVal }
    Write-Host "      cooling $cool s ..."
    Start-Sleep -Seconds $cool

    Write-Host "      $($script:RepeatVal) timed probes ..."
    Invoke-Capture -Label $id -PromptFile $a.prompt -Events $ev -Reps $script:RepeatVal -Settle $script:SettleVal
    $v1 = Get-Vram
    Stop-Server

    $json = Join-Path $script:MDIR ("arm-$id.json")
    $r = Invoke-Attribute -Label $id -EventFiles @($ev) -JsonOut $json -DropFirst
    $cfg = $a.cfg
    if ($CfgSuffix -ne '') { $cfg = $cfg + '; ' + $CfgSuffix }
    Write-ArmResult -Id $id -R $r -Mode 'phase-split' -Cfg $cfg -Vram $v1
}

function Invoke-IdleArm {
    param($a)
    Stop-Server
    Start-Sleep -Seconds 5
    $t0 = (Get-Date).ToString('yyyy-MM-ddTHH:mm:ss.fff')
    Write-Host "      idle window $($script:IdleWindowVal) s (no server) ..."
    Start-Sleep -Seconds $script:IdleWindowVal
    $t1 = (Get-Date).ToString('yyyy-MM-ddTHH:mm:ss.fff')
    $json = Join-Path $script:MDIR ("arm-$($a.id).json")
    $r = Invoke-Attribute -Label $a.id -WinT0 $t0 -WinT1 $t1 -JsonOut $json
    Write-ArmResult -Id $a.id -R $r -Mode 'window-idle' -Cfg $a.cfg -Vram (Get-Vram) -Extra "t0=$t0 t1=$t1"
}

function Invoke-LoadedIdleArm {
    param($a)
    $srv = Start-Server -Model $a.model -Extra (Build-SrvArgs $a) -Tag $a.id
    if ($null -eq $srv) { Write-Log "FAILED $($a.id) reason=server-load"; return }
    $v0 = Get-Vram
    Write-Log ("  LOAD $($a.id) load_s=$($srv.load_s) vram_board=$($v0.board_mib) vram_ded=$($v0.srv_ded_mib) vram_shr=$($v0.srv_shr_mib)")
    Start-Sleep -Seconds 10   # let the load transient decay before the window opens
    $t0 = (Get-Date).ToString('yyyy-MM-ddTHH:mm:ss.fff')
    Write-Host "      loaded-idle window $($script:IdleWindowVal) s (server up, zero requests) ..."
    Start-Sleep -Seconds $script:IdleWindowVal
    $t1 = (Get-Date).ToString('yyyy-MM-ddTHH:mm:ss.fff')
    $v1 = Get-Vram
    Stop-Server
    $json = Join-Path $script:MDIR ("arm-$($a.id).json")
    $r = Invoke-Attribute -Label $a.id -WinT0 $t0 -WinT1 $t1 -JsonOut $json
    Write-ArmResult -Id $a.id -R $r -Mode 'window-idle' -Cfg $a.cfg -Vram $v1 -Extra "t0=$t0 t1=$t1"
}

function Get-BurstWindow {
    # min t_start / max t_end and the token totals across a set of event files.
    param([string[]]$Files)
    $t0 = $null; $t1 = $null; $dec = 0; $pro = 0; $n = 0; $starts = @()
    foreach ($f in $Files) {
        foreach ($e in (Read-Events $f)) {
            if ($null -eq $e.t_start_iso) { continue }
            $s = [datetime]::ParseExact([string]$e.t_start_iso, 'yyyy-MM-ddTHH:mm:ss.fff', $null)
            $en = $s
            if ($null -ne $e.t_end_iso) { $en = [datetime]::ParseExact([string]$e.t_end_iso, 'yyyy-MM-ddTHH:mm:ss.fff', $null) }
            $starts += $s
            if ($null -eq $t0) { $t0 = $s } elseif ($s -lt $t0) { $t0 = $s }
            if ($null -eq $t1) { $t1 = $en } elseif ($en -gt $t1) { $t1 = $en }
            if ($null -ne $e.predicted_n) { $dec += [int]$e.predicted_n }
            if ($null -ne $e.prompt_n)    { $pro += [int]$e.prompt_n }
            $n++
        }
    }
    $skew = 0.0
    if ($starts.Count -gt 1) {
        $mn = ($starts | Sort-Object | Select-Object -First 1)
        $mx = ($starts | Sort-Object | Select-Object -Last 1)
        $skew = [math]::Round(($mx - $mn).TotalMilliseconds, 0)
    }
    return [pscustomobject]@{
        t0 = $(if ($null -eq $t0) { '' } else { $t0.ToString('yyyy-MM-ddTHH:mm:ss.fff') })
        t1 = $(if ($null -eq $t1) { '' } else { $t1.ToString('yyyy-MM-ddTHH:mm:ss.fff') })
        dec = $dec; pro = $pro; n = $n; skew_ms = $skew
    }
}

function Invoke-CoarseSeqArm {
    param($a)
    $warm = Join-Path $script:EVDIR ("raw-events-$($a.id)-warm.jsonl")
    $ev   = Join-Path $script:EVDIR ("raw-events-$($a.id).jsonl")
    Remove-Item -LiteralPath $warm, $ev -ErrorAction SilentlyContinue
    $srv = Start-Server -Model $a.model -Extra (Build-SrvArgs $a) -Tag $a.id
    if ($null -eq $srv) { Write-Log "FAILED $($a.id) reason=server-load"; return }
    $v0 = Get-Vram
    Write-Log ("  LOAD $($a.id) load_s=$($srv.load_s) vram_board=$($v0.board_mib) vram_shr=$($v0.srv_shr_mib)")
    Invoke-Capture -Label "$($a.id)-warm" -PromptFile $a.prompt -Events $warm -Reps 1
    Start-Sleep -Seconds $script:CooldownVal
    Invoke-Capture -Label $a.id -PromptFile $a.prompt -Events $ev -Reps 2 -Settle 0
    $v1 = Get-Vram
    Stop-Server
    $w = Get-BurstWindow -Files @($ev)
    if ($w.t0 -eq '') { Write-Log "FAILED $($a.id) reason=no-events"; return }
    $json = Join-Path $script:MDIR ("arm-$($a.id).json")
    $r = Invoke-Attribute -Label $a.id -WinT0 $w.t0 -WinT1 $w.t1 -WinTokens ("$($w.dec)/$($w.pro)") -JsonOut $json
    Write-ArmResult -Id $a.id -R $r -Mode 'window-coarse' -Cfg $a.cfg -Vram $v1 `
        -Extra "requests=$($w.n) start_skew_ms=$($w.skew_ms) t0=$($w.t0) t1=$($w.t1) NOTE=coarse-window-includes-prefill"
}

function Invoke-CoarseParArm {
    param($a)
    $warm = Join-Path $script:EVDIR ("raw-events-$($a.id)-warm.jsonl")
    $evA  = Join-Path $script:EVDIR ("raw-events-$($a.id)-a.jsonl")
    $evB  = Join-Path $script:EVDIR ("raw-events-$($a.id)-b.jsonl")
    Remove-Item -LiteralPath $warm, $evA, $evB -ErrorAction SilentlyContinue
    $srv = Start-Server -Model $a.model -Extra (Build-SrvArgs $a) -Tag $a.id
    if ($null -eq $srv) { Write-Log "FAILED $($a.id) reason=server-load"; return }
    $v0 = Get-Vram
    Write-Log ("  LOAD $($a.id) load_s=$($srv.load_s) vram_board=$($v0.board_mib) vram_shr=$($v0.srv_shr_mib)")
    Invoke-Capture -Label "$($a.id)-warm" -PromptFile $a.prompt -Events $warm -Reps 1
    Start-Sleep -Seconds $script:CooldownVal

    # Two jobs, each spinning until the SAME absolute instant, so the two POSTs
    # land within tens of ms of each other instead of one PowerShell start-up
    # apart. Separate event files: two writers, one file, would interleave.
    $go = (Get-Date).AddSeconds(20)
    $sb = {
        param($cap, $ticks, $label, $promptFile, $events, $base, $outDir, $np, $model)
        while ((Get-Date).Ticks -lt $ticks) { Start-Sleep -Milliseconds 20 }
        & $cap -Label $label -PromptFile $promptFile -Events $events -BaseUrl $base `
            -OutDir $outDir -NPredict $np -Temp 0 -TopK 1 -Chat -Model $model -Repeat 1
    }
    $jobs = @()
    $jobs += Start-Job -ScriptBlock $sb -ArgumentList $script:CAPTURE, $go.Ticks, "$($a.id)-a", $a.prompt, $evA, $script:BASE, $script:EVDIR, $script:NPredictVal, $script:ALIAS
    $jobs += Start-Job -ScriptBlock $sb -ArgumentList $script:CAPTURE, $go.Ticks, "$($a.id)-b", $a.prompt, $evB, $script:BASE, $script:EVDIR, $script:NPredictVal, $script:ALIAS
    Wait-Job -Job $jobs -Timeout 1800 | Out-Null
    foreach ($j in $jobs) {
        foreach ($l in @(Receive-Job -Job $j -ErrorAction SilentlyContinue)) { Write-Host ("      | " + $l) }
        Remove-Job -Job $j -Force -ErrorAction SilentlyContinue
    }
    $v1 = Get-Vram
    Stop-Server

    $w = Get-BurstWindow -Files @($evA, $evB)
    if ($w.t0 -eq '') { Write-Log "FAILED $($a.id) reason=no-events"; return }
    $json = Join-Path $script:MDIR ("arm-$($a.id).json")
    $r = Invoke-Attribute -Label $a.id -WinT0 $w.t0 -WinT1 $w.t1 -WinTokens ("$($w.dec)/$($w.pro)") -JsonOut $json
    Write-ArmResult -Id $a.id -R $r -Mode 'window-coarse' -Cfg $a.cfg -Vram $v1 `
        -Extra "requests=$($w.n) start_skew_ms=$($w.skew_ms) t0=$($w.t0) t1=$($w.t1) NOTE=coarse-window-includes-prefill"
}

function Invoke-PlimitArm {
    param($a)
    $cmd = "nvidia-smi -pl $($a.plimit)"
    if ($script:SkipPL) {
        Write-Log "SKIPPED $($a.id) reason=skipped-by-flag cmd=`"$cmd`" cfg=`"$($a.cfg)`""
        return
    }
    if (-not $script:PL_OK) {
        Write-Log ("SKIPPED $($a.id) reason=needs-admin note=`"GPU power cap is the one knob unmeasured on this machine; " +
                   "stock default limit $(Inv $script:PL_DEFAULT 0) W`" cmd=`"$cmd`" restore=`"nvidia-smi -pl $(Inv $script:PL_DEFAULT 0)`" probe_msg=`"$($script:PL_MSG)`" cfg=`"$($a.cfg)`"")
        return
    }
    $win = Get-BestSpecArm
    if ($null -eq $win) {
        Write-Log "SKIPPED $($a.id) reason=no-B-results note=`"run section B first - H needs its winner`" cmd=`"$cmd`""
        return
    }
    $base = Get-ArmById $win.id
    if ($null -eq $base) { Write-Log "SKIPPED $($a.id) reason=winner-not-in-table winner=$($win.id)"; return }
    $set = Set-PowerLimit -Watts $a.plimit
    if (-not $set.ok) {
        Write-Log "SKIPPED $($a.id) reason=plimit-set-failed exit=$($set.exit) msg=`"$($set.msg)`" cmd=`"$cmd`""
        return
    }
    $script:PL_CHANGED = $true
    Write-Log "  PLIMIT $($a.id) set to $($a.plimit) W (now=$(Inv $set.now_w 0) W, default=$(Inv $script:PL_DEFAULT 0) W) via `"$cmd`""
    # clone the winner's config; only the cap differs
    $clone = @{}
    foreach ($k in $base.Keys) { $clone[$k] = $base[$k] }
    $clone.prompt = $a.prompt
    $clone.cfg = "$($base.cfg); power cap $($a.plimit) W (winner=$($win.id))"
    Invoke-ReqArm -a $clone -IdOverride $a.id -CfgSuffix ''
}

function Restore-PowerLimit {
    if (-not $script:PL_CHANGED) { return }
    if ($null -eq $script:PL_DEFAULT) { return }
    $w = [int][math]::Round([double]$script:PL_DEFAULT, 0)
    $r = Set-PowerLimit -Watts $w
    if ($r.ok) {
        Write-Log "  PLIMIT restored to default $w W (now=$(Inv $r.now_w 0) W)"
        $script:PL_CHANGED = $false
    } else {
        Write-Log "  PLIMIT RESTORE FAILED exit=$($r.exit) msg=`"$($r.msg)`" - run: nvidia-smi -pl $w"
    }
}

# ===================================================================== plan
function Show-Plan {
    param($Arms, [bool]$ShowDone)
    $tot = 0; $pend = 0; $ndone = 0
    Write-Host ''
    Write-Host '  ARM                          EST     STATUS  CONFIG'
    Write-Host '  ---------------------------  ------  ------  ------------------------------------------'
    foreach ($a in $Arms) {
        $tot += [int]$a.est
        $done = $false
        if ($ShowDone) { $done = Test-ArmDone $a.id }
        $st = 'pending'
        if ($done) { $st = 'done'; $ndone++ } else { $pend += [int]$a.est }
        $mm = [math]::Floor([int]$a.est / 60)
        $ss = [int]$a.est % 60
        Write-Host ("  {0,-27}  {1,2}:{2:00}  {3,-7}  {4}" -f $a.id, $mm, $ss, $st, $a.desc)
    }
    Write-Host '  ---------------------------  ------  -------  -----------------------------------------'
    Write-Host ("  FULL MATRIX   : {0} arms, estimated {1} min ({2} s)" -f $Arms.Count, [math]::Round($tot / 60.0, 1), $tot)
    Write-Host ("  ALREADY DONE  : {0} arm(s)" -f $ndone)
    Write-Host ("  THIS RUN      : {0} arm(s), ESTIMATED WALL CLOCK {1} min ({2} s)" -f ($Arms.Count - $ndone), [math]::Round($pend / 60.0, 1), $pend)
    Write-Host ''
    Write-Host '  Estimates are derived from the campaign''s measured t/s and load times; the'
    Write-Host '  depth arms dominate because prompt caching is OFF, so every probe re-prefills.'
    Write-Host ''
    return $pend
}

function Show-Matrix {
    Write-Host ''
    Write-Host '=== MATRIX SO FAR ============================================================'
    foreach ($l in (Get-LogLines)) {
        if ($l -match '^(RESULT|SKIPPED) ') { Write-Host $l }
    }
    Write-Host '=============================================================================='
}

# ==================================================================== detach
if ($Detach) {
    $fwd = @('-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', ('"' + $PSCommandPath + '"'))
    foreach ($k in $PSBoundParameters.Keys) {
        if ($k -eq 'Detach') { continue }
        $v = $PSBoundParameters[$k]
        if ($v -is [System.Management.Automation.SwitchParameter]) {
            if ($v.IsPresent) { $fwd += "-$k" }
        } else {
            $fwd += @("-$k", ('"' + [string]$v + '"'))
        }
    }
    Ensure-Dir $script:MDIR
    $p = Start-Process -FilePath 'powershell.exe' -ArgumentList $fwd -WindowStyle Hidden -PassThru
    Set-Content -LiteralPath $script:PIDFILE -Value "$($p.Id)" -Encoding ascii
    Write-Host "DETACHED pid=$($p.Id)"
    Write-Host "  result log : $($script:LOG)"
    Write-Host "  console    : $(Join-Path $script:MDIR 'console-*.log')"
    Write-Host "  stop it    : Stop-Process -Id $($p.Id)   (then re-run to resume)"
    return
}

# ================================================================== bootstrap
Ensure-Dir $script:MDIR
Ensure-Dir $script:EVDIR
Ensure-Dir $script:PDIR
Ensure-Dir $script:SRVDIR
if (-not (Test-Path -LiteralPath $script:LOG)) { New-Item -ItemType File -Path $script:LOG | Out-Null }

$script:LoadModeVal      = $LoadMode
$script:PortVal          = $Port
$script:NPredictVal      = $NPredict
$script:RepeatVal        = $Repeat
$script:CooldownVal      = $CooldownSec
$script:DepthCooldownVal = $DepthCooldownSec
$script:SettleVal        = $SettleSec
$script:IdleWVal         = $IdleW
$script:IdleWindowVal    = $IdleWindowSec
$script:SkipPL           = [bool]$SkipPowerLimit

$promptMap  = New-PromptFiles
$script:ARMS = Get-Arms -P $promptMap

# subset / redo selection
$onlyList = @()
if ($Only -ne '') { $onlyList = @(($Only -split ',') | ForEach-Object { $_.Trim() } | Where-Object { $_ -ne '' }) }
$redoList = @()
if ($Redo -ne '') { $redoList = @(($Redo -split ',') | ForEach-Object { $_.Trim() } | Where-Object { $_ -ne '' }) }

$selected = @()
foreach ($a in $script:ARMS) {
    if ($onlyList.Count -gt 0 -and ($onlyList -notcontains $a.id)) { continue }
    $selected += $a
}
if ($selected.Count -eq 0) {
    Write-Host "no arms selected. Known ids:"
    foreach ($a in $script:ARMS) { Write-Host "  $($a.id)" }
    return
}

# power-limit capability probe (harmless: it re-asserts the card's own default)
$pl = Get-PowerLimits
$script:PL_DEFAULT = $pl.default_w
$elev = Test-Elevated

# ------------------------------------------------------------------- header
Write-Host ''
Write-Host '=============================================================================='
Write-Host ' POWER MATRIX - Qwen3.8-27B on RTX 3090'
Write-Host ' tier: in-band GPU BOARD power (NVML via nvidia-smi). PSU losses, CPU/RAM/'
Write-Host '       drives/display and PUE are EXCLUDED and UNMEASURED on this machine.'
Write-Host '=============================================================================='
Write-Host " started      : $($script:T_BEGIN.ToString('yyyy-MM-dd HH:mm:ss'))"
Write-Host " result log   : $($script:LOG)   (resumable: RESULT/SKIPPED lines are skipped)"
Write-Host " power csv dir: $($script:PDIR)"
Write-Host " artifacts    : $($script:MDIR)"
Write-Host " server       : $($script:EXE) on port $Port   load-mode=$LoadMode"
Write-Host " probe        : $NPredict answer tokens, temp 0 / top_k 1, cache_prompt=OFF"
Write-Host " protocol     : 1 discarded probe -> cooldown -> $Repeat timed probes -> --drop-first"
Write-Host " idle-w       : $(Inv $IdleW 2) W used for idle subtraction"
Write-Host " elevated     : $elev   (GPU power cap needs admin)"
Write-Host " pl default   : $(Inv $script:PL_DEFAULT 0) W   current $(Inv $pl.current_w 0) W"

$pending = Show-Plan -Arms $selected -ShowDone $true

if ($Plan) {
    Write-Host 'PLAN ONLY - nothing was started, no GPU or server was touched.'
    $running = Get-LlamaProcs
    if ($running.Count -gt 0) {
        Write-Host ''
        Write-Host " NOTE: $($running.Count) llama-server process(es) are running right now:"
        foreach ($p in $running) { Write-Host "   pid=$($p.Id) started=$($p.Started)" }
        Write-Host ' A real run would REFUSE to start while that is true (use -Force to override).'
    }
    return
}

# ---------------------------------------------------------------- preflight
$running = Get-LlamaProcs
if ($running.Count -gt 0 -and -not $Force) {
    Write-Host ''
    Write-Host 'REFUSED a llama-server is already running - that is very likely the rule-21'
    Write-Host '        benchmark sweep. This matrix restarts the server for every arm and'
    Write-Host '        would destroy it. Wait for the sweep, or pass -Force if you are sure.'
    foreach ($p in $running) { Write-Host "        pid=$($p.Id) started=$($p.Started)" }
    return
}
if (Test-Path -LiteralPath $script:PIDFILE) {
    $old = 0
    try { $old = [int](Get-Content -LiteralPath $script:PIDFILE -Raw).Trim() } catch { $old = 0 }
    if ($old -gt 0 -and $old -ne $PID) {
        $op = Get-Process -Id $old -ErrorAction SilentlyContinue
        if ($null -ne $op -and -not $Force) {
            Write-Host "REFUSED another power-matrix run looks alive (pid=$old). Use -Force to override."
            return
        }
    }
}
Set-Content -LiteralPath $script:PIDFILE -Value "$PID" -Encoding ascii

# python
$pyok = $false
try { $pv = (& $script:PY --version 2>&1 | Out-String).Trim(); if ($LASTEXITCODE -eq 0) { $pyok = $true } } catch { }
if (-not $pyok) {
    try { $pv = (& py -3 --version 2>&1 | Out-String).Trim(); if ($LASTEXITCODE -eq 0) { $script:PY = 'py'; $pyok = $true } } catch { }
}
if (-not $pyok) { Write-Host 'REFUSED python not runnable - attribute-power.py cannot run.'; Remove-Item -LiteralPath $script:PIDFILE -ErrorAction SilentlyContinue; return }
Write-Host " python       : $pv"

# transcript for the detached case
$console = Join-Path $script:MDIR "console-$($script:STAMP).log"
try { Start-Transcript -Path $console -Append | Out-Null } catch { }

# stale cap left by a previous crashed run
if ($null -ne $pl.current_w -and $null -ne $pl.default_w) {
    if ([math]::Abs([double]$pl.current_w - [double]$pl.default_w) -gt 1.0) {
        Write-Log "  WARN GPU power limit is $(Inv $pl.current_w 0) W, not the default $(Inv $pl.default_w 0) W - restoring first"
        $script:PL_CHANGED = $true
        Restore-PowerLimit
    }
}

# power-limit probe: setting the limit to the card's own default changes nothing
if (-not $script:SkipPL) {
    if ($elev -and $null -ne $script:PL_DEFAULT) {
        $probe = Set-PowerLimit -Watts ([int][math]::Round([double]$script:PL_DEFAULT, 0))
        $script:PL_OK  = $probe.ok
        $script:PL_MSG = $probe.msg
    } else {
        $script:PL_OK  = $false
        $script:PL_MSG = 'shell is not elevated'
    }
}

# logger
$script:POWERCSV = Join-Path $script:PDIR ("power-matrix-$($script:STAMP).csv")
Write-Host ''
Write-Host "starting power logger -> $($script:POWERCSV)"
& $script:SAMPLE -Start -Csv $script:POWERCSV -IntervalMs 500 | ForEach-Object { Write-Host "  $_" }
Start-Sleep -Seconds 2
$loggerOk = $false
if (Test-Path -LiteralPath $script:POWERCSV) { if ((Get-Item -LiteralPath $script:POWERCSV).Length -gt 0) { $loggerOk = $true } }
if (-not $loggerOk -and -not $Force) {
    Write-Host 'REFUSED the power logger produced no samples - there would be nothing to attribute.'
    try { Stop-Transcript | Out-Null } catch { }
    Remove-Item -LiteralPath $script:PIDFILE -ErrorAction SilentlyContinue
    return
}

Add-LogLine ''
Add-LogLine "# ===== RUN $($script:STAMP) pid=$PID ====="
Add-LogLine "# tier=in-band GPU board power (NVML); PSU/wall/PUE excluded and unmeasured"
Add-LogLine "# power_csv=$($script:POWERCSV) idle_w=$(Inv $IdleW 2) n_predict=$NPredict repeat=$Repeat"
Add-LogLine "# protocol=1 discarded probe + $CooldownSec s cooldown ($DepthCooldownSec s deep) + $Repeat timed probes, --drop-first, cache_prompt=off"
Add-LogLine "# server=$($script:EXE) port=$Port load-mode=$LoadMode ngl=99"
Add-LogLine "# elevated=$elev pl_ok=$($script:PL_OK) pl_default_w=$(Inv $script:PL_DEFAULT 0)"
Add-LogLine "# estimated wall for this run: $([math]::Round($pending / 60.0, 1)) min"

# ======================================================================= run
$done = 0; $skipped = 0
try {
    foreach ($a in $selected) {
        if ((Test-ArmDone $a.id) -and ($redoList -notcontains $a.id)) {
            Write-Host "SKIP (already in log) $($a.id)"
            $skipped++
            continue
        }
        Write-Host ''
        Write-Host "=== $($a.id)  $(Get-Date -Format 'HH:mm:ss')  est $([math]::Round([int]$a.est / 60.0, 1)) min ==="
        Write-Host "    $($a.desc)"
        $t0 = Get-Date
        try {
            switch ($a.kind) {
                'idle'        { Invoke-IdleArm       -a $a }
                'loaded-idle' { Invoke-LoadedIdleArm -a $a }
                'req'         { Invoke-ReqArm        -a $a }
                'coarse-seq'  { Invoke-CoarseSeqArm  -a $a }
                'coarse-par'  { Invoke-CoarseParArm  -a $a }
                'plimit'      { Invoke-PlimitArm     -a $a }
                default       { Write-Log "FAILED $($a.id) reason=unknown-kind=$($a.kind)" }
            }
        } catch {
            Write-Log "FAILED $($a.id) reason=exception msg=`"$(($_.Exception.Message) -replace '\s+', ' ')`""
            Stop-Server
        }
        $el = [math]::Round(((Get-Date) - $t0).TotalSeconds, 0)
        Write-Host "    arm wall $el s (est $($a.est) s)"
        $done++
        Start-Sleep -Seconds $InterArmSec
    }
} finally {
    Restore-PowerLimit
    Stop-Server
    Write-Host ''
    Write-Host "stopping power logger $($script:POWERCSV)"
    try { & $script:SAMPLE -Stop -Csv $script:POWERCSV | ForEach-Object { Write-Host "  $_" } } catch { }

    # combined report over every phase-split arm run so far
    try {
        $evs = @()
        foreach ($f in @(Get-ChildItem -LiteralPath $script:EVDIR -Filter 'events-*.jsonl' -ErrorAction SilentlyContinue | Sort-Object Name)) {
            if ($f.Length -gt 0) { $evs += $f.FullName }
        }
        $csvs = Get-PowerCsvs
        if ($evs.Count -gt 0 -and $csvs.Count -gt 0) {
            $pa = @($script:ATTRIB)
            foreach ($p in $csvs) { $pa += @('--power', $p) }
            foreach ($e in $evs)  { $pa += @('--events', $e) }
            $pa += @('--idle-w', (Inv $script:IdleWVal), '--drop-first',
                     '--json',    (Join-Path $script:MDIR 'arms.json'),
                     '--csv-out', (Join-Path $script:MDIR 'arms.csv'))
            $rep = & $script:PY @pa 2>&1
            $txt = ($rep | Out-String)
            [System.IO.File]::WriteAllText((Join-Path $script:MDIR 'report.txt'), $txt, (New-Object System.Text.UTF8Encoding($false)))
            Write-Host $txt
            Write-Host "wrote $(Join-Path $script:MDIR 'report.txt') / arms.json / arms.csv"
        }
    } catch {
        Write-Host "combined report failed: $($_.Exception.Message)"
    }

    Show-Matrix
    $wall = [math]::Round(((Get-Date) - $script:T_BEGIN).TotalMinutes, 1)
    Write-Host ''
    Write-Host "ran $done arm(s), skipped $skipped already-done, wall $wall min (estimated $([math]::Round($pending / 60.0, 1)) min)"
    Write-Host 'REMINDER every figure above is in-band GPU BOARD power (NVML). PSU conversion'
    Write-Host '         loss, the rest of the node and PUE are excluded and unmeasured here.'
    Remove-Item -LiteralPath $script:PIDFILE -ErrorAction SilentlyContinue
    try { Stop-Transcript | Out-Null } catch { }
}
