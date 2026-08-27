# Follow-up M1 - IQ4_XS-specific MTP flag re-sweep on a REALISTIC NOVEL code probe.
#
# Why: the shipped tuned flags (draft-mtp n-max 4 / p-min 0.75) were tuned on
# Q4_K_M with a textbook red-black-tree prompt. This re-sweeps them on the
# UD-IQ4_XS file with a prompt that cannot be memorised, and runs the SAME
# sweep on Q4_K_M under identical conditions so "does IQ4_XS prefer different
# flags?" is answered by a matched pair, not by comparing to old numbers.
#
# Conditions (identical for every row):
#   -c 32768, -ngl 99, --parallel 1, --load-mode mmap, -ctk q8_0 -ctv q8_0,
#   --jinja, thinking DISABLED (so the timed tokens are the code, not
#   reasoning -- the phase3d correction), temp 0 / top_k 1, max_tokens 700.
#   Fresh server per config (the spec flags are load-time).
#   Two identical probes per server: probe 2 hits the prefix cache for prefill
#   but decodes the same 700 greedy tokens again -> a clean repeat of the
#   decode rate, same token stream.
# Speed numbers come from the server's own timings, never wall-clock.
$ErrorActionPreference = 'Continue'
. 'E:\AI\measured-inference\results\qwen38-27b-blind\work\lib.ps1'
$script:DATA = 'E:\AI\measured-inference\results\qwen38-27b-blind\data\followup'
$out = Join-Path $script:DATA 'm1-mtp-resweep.txt'
if (-not (Test-Path $out)) { New-Item -ItemType File -Path $out | Out-Null }
$done = Get-Content $out -ErrorAction SilentlyContinue

$IQ4 = 'C:\Users\chink\.lmstudio\models\unsloth\Qwen3.8-27B-GGUF\Qwen3.8-27B-UD-IQ4_XS.gguf'
$QKM = 'C:\Users\chink\.lmstudio\models\lmstudio-community\Qwen3.8-27B-GGUF\Qwen3.8-27B-Q4_K_M.gguf'

$common  = @('-c','32768','-ngl','99','--parallel','1','--load-mode','mmap','-ctk','q8_0','-ctv','q8_0')
$NOTHINK = @('--chat-template-kwargs', '{\"enable_thinking\":false}')

# Realistic novel code: a specific internal-service module, not a textbook
# algorithm. No public reference implementation exists to be memorised.
$NOVEL = 'Write a single self-contained Python module named tenant_ratelimit.py implementing a sliding-window rate limiter keyed by (tenant_id, endpoint). Requirements: window size and quota configurable per endpoint with per-tenant overrides supplied as a dict at construction; monotonic-clock based so wall-clock changes cannot be exploited; thread-safe under concurrent callers; amortised O(1) memory per key by evicting expired timestamps lazily; a decorator @limited(endpoint) that raises RateLimitExceeded carrying retry_after_seconds; and a structured JSON audit record emitted on every denial. Include a __main__ block that exercises burst, steady-state and per-tenant override behaviour. Code only, no explanation.'

$cfgs = @(
    @{ tag='none';      extra=@('--spec-type','none') },
    @{ tag='n2-p0.75';  extra=@('--spec-type','draft-mtp','--spec-draft-n-max','2','--spec-draft-p-min','0.75') },
    @{ tag='n3-p0.75';  extra=@('--spec-type','draft-mtp','--spec-draft-n-max','3','--spec-draft-p-min','0.75') },
    @{ tag='n4-p0.75';  extra=@('--spec-type','draft-mtp','--spec-draft-n-max','4','--spec-draft-p-min','0.75') },
    @{ tag='n6-p0.5';   extra=@('--spec-type','draft-mtp','--spec-draft-n-max','6','--spec-draft-p-min','0.5') },
    @{ tag='n10-p0.5';  extra=@('--spec-type','draft-mtp','--spec-draft-n-max','10','--spec-draft-p-min','0.5') },
    @{ tag='n10-p0.75'; extra=@('--spec-type','draft-mtp','--spec-draft-n-max','10','--spec-draft-p-min','0.75') }
)

$quants = @(
    @{ q='IQ4_XS'; path=$IQ4 },
    @{ q='Q4_K_M'; path=$QKM }
)

function Acc { param($r)
    if ($r.draft_n -and [double]$r.draft_n -gt 0) { return [math]::Round([double]$r.draft_acc / [double]$r.draft_n, 4) }
    return 'n/a'
}

foreach ($qq in $quants) {
    $script:MODEL = $qq.path
    foreach ($c in $cfgs) {
        $row = "$($qq.q)/$($c.tag)"
        if ($done -match ("^RESULT " + [regex]::Escape($row) + " ")) { Write-Host "skip $row"; continue }
        Write-Host ("=== {0}  {1} ===" -f $row, (Get-Date -Format 'HH:mm:ss'))
        $s = Start-Srv -Extra ($common + $NOTHINK + $c.extra) -Tag ("m1-" + ($row -replace '[\\/]','-')) -TimeoutSec 600
        if (-not $s) { Write-Row $out ("RESULT {0} LOAD-FAILED" -f $row); continue }
        $v = Get-Vram
        [void](Invoke-Probe -Text 'Say OK.' -MaxTokens 16)   # warm-up, not measured
        $r1 = Invoke-Probe -Text $NOVEL -MaxTokens 700
        $r2 = Invoke-Probe -Text $NOVEL -MaxTokens 700
        Write-Row $out ("RESULT {0} decode_tps_1={1} decode_tps_2={2} accept_1={3} accept_2={4} draft_n_1={5} draft_acc_1={6} predicted_n_1={7} predicted_n_2={8} prompt_n={9} prefill_tps_1={10} answer_chars={11} think_chars={12} finish={13} board_mib={14} ded_mib={15} shr_mib={16}" -f `
            $row, $r1.decode_tps, $r2.decode_tps, (Acc $r1), (Acc $r2), $r1.draft_n, $r1.draft_acc, `
            $r1.predicted_n, $r2.predicted_n, $r1.prompt_n, $r1.prefill_tps, $r1.text.Length, $r1.think.Length, $r1.finish, `
            $v.board_mib, $v.srv_ded_mib, $v.srv_shr_mib)
        $head = ($r1.text -replace "`r?`n", ' ')
        if ($head.Length -gt 120) { $head = $head.Substring(0,120) }
        Write-Row $out ("  HEAD {0}| {1}" -f $row, $head)
        Stop-Srv
    }
}
Stop-Srv
Write-Host 'M1 DONE'
