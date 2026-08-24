# drafter-at-2bit.ps1 - does the built-in MTP draft head still work below 4 bits?
#
# THE QUESTION, and it is the one that decides a daily-driver swap. The accuracy
# ladder proved UD-Q2_K_XL (9.154 GiB, 2.912 bpw) is indistinguishable from the
# shipped UD-IQ4_XS (13.274 GiB) on task accuracy - paired McNemar, 1 discordant
# item of 75, p=1.0. It is 4.12 GiB smaller. On the bandwidth law that should
# make it ~1.45x faster, and the one cold probe we have says only 1.15x.
#
# BUT every recipe this campaign ships runs the MTP drafter ON, worth ~2.18x on
# code - far more than the size difference. NOBODY HAS MEASURED whether the
# draft head still earns that below 4 bits. If acceptance collapses at 2.9 bpw,
# the smaller file is SLOWER in practice than the bigger one, and the swap is
# wrong however good its accuracy looks.
#
# Rule 11: report mean draft length BESIDE acceptance - the highest-acceptance
# config can be the slowest, and draft length is the throughput predictor.
# Rule 12: discard the first post-prefill probe; time only settled probes.
# Rule 25 who-consumes: the reader-facing number is the daily-driver
# recommendation in section 03 of the published guide.
#
# Four loads, matched: {IQ4_XS, Q2_K_XL} x {drafter off, drafter on}.
param(
    [int]$DeadlineMinutes = 90,
    [int]$MaxVramMiB = 2000
)
$ErrorActionPreference = 'Continue'
$here = 'E:\AI\measured-inference\scripts\quant-ladder'
. (Join-Path $here 'ladder-lib.ps1')

$M    = 'C:\Users\chink\.lmstudio\models\unsloth\Qwen3.8-27B-GGUF'
$DATA = 'E:\AI\measured-inference\results\qwen38-27b-blind\data\quant-ladder'
$OUT  = Join-Path $DATA 'drafter-2bit'
if (-not (Test-Path $OUT)) { New-Item -ItemType Directory -Path $OUT -Force | Out-Null }
$LED = Join-Path $OUT 'drafter-2bit.txt'
if (-not (Test-Path $LED)) {
    Set-Content -LiteralPath $LED -Encoding utf8 -Value ('# does the MTP drafter survive below 4 bits - opened {0}' -f (Get-Date -Format 's'))
}
$PORT = 1235
$DEADLINE = (Get-Date).AddMinutes($DeadlineMinutes)

# A novel coding prompt: textbook algorithms inflate a draft head's hit rate,
# so this is the same class of prompt round 2's matched sweep used.
$PROMPT = @'
Write a single self-contained JavaScript module that implements a fixed-window
rate limiter with a pluggable clock, a per-key limit, and an eviction sweep that
runs at most once per window. Include JSDoc on every exported symbol and a short
usage example at the end. Do not explain the code outside the module.
'@

$FILES = @(
    @{ tag = 'iq4xs';  path = "$M\Qwen3.8-27B-UD-IQ4_XS.gguf";  gib = 13.274 },
    @{ tag = 'q2kxl';  path = "$M\Qwen3.8-27B-UD-Q2_K_XL.gguf"; gib = 9.154  }
)
$SPECS = @(
    @{ tag = 'off'; flags = @('--spec-type','none') },
    @{ tag = 'on';  flags = @('--spec-type','draft-mtp','--spec-draft-n-max','10','--spec-draft-p-min','0.5') }
)

function Wait-Idle {
    while ((Get-Date) -lt $DEADLINE) {
        $procs = @(Get-Process -Name 'llama-server','llama-perplexity','llama-cli','llama-bench' -ErrorAction SilentlyContinue).Count
        $vram = 999999
        try { $vram = [int](& nvidia-smi --query-gpu=memory.used --format=csv,noheader,nounits | Select-Object -First 1) } catch {}
        if ($procs -eq 0 -and $vram -lt $MaxVramMiB) { return $true }
        Write-Log ('waiting for the card - llamaProcs={0} vram={1}' -f $procs, $vram)
        Start-Sleep -Seconds 60
    }
    return $false
}

Write-Log 'DRAFTER-AT-2BIT: waiting for the accuracy ladder to release the card'
if (-not (Wait-Idle)) { Write-Log 'deadline before the card freed - NOT run'; exit 2 }

foreach ($f in $FILES) {
    foreach ($s in $SPECS) {
        if ((Get-Date) -ge $DEADLINE) { break }
        $tag = '{0}-{1}' -f $f.tag, $s.tag
        if (Test-LedgerHas $LED ('PAIR ' + $tag + ' ')) { Write-Log ('skip ' + $tag); continue }
        $flags = @('-ngl','99','-c','32768','-fa','on','--parallel','1',
                   '-ctk','q8_0','-ctv','q8_0','--jinja','--reasoning','off') + $s.flags
        $srv = Start-Srv -ModelPath $f.path -Tag ('d2b-' + $tag) -Flags $flags -Port $PORT -LogDir $OUT
        if (-not $srv) { Write-Ledger $LED ('PAIR {0} | SRVFAIL' -f $tag); continue }
        # rule 12: the first probe after load/prefill reads low - discard it.
        $null = Invoke-Probe -Text $PROMPT -MaxTokens 700 -Port $PORT -TimeoutSec 600
        Start-Sleep -Seconds 5
        $rs = @()
        for ($i = 0; $i -lt 3; $i++) {
            $r = Invoke-Probe -Text $PROMPT -MaxTokens 700 -Port $PORT -TimeoutSec 600
            if ($r.ok) { $rs += $r }
            Start-Sleep -Seconds 3
        }
        Stop-Srv
        if (-not $rs.Count) { Write-Ledger $LED ('PAIR {0} | NOPROBE' -f $tag); continue }
        $tps = ($rs | Measure-Object -Property decode_tps -Average).Average
        $mn  = ($rs | Measure-Object -Property decode_tps -Minimum).Minimum
        $mx  = ($rs | Measure-Object -Property decode_tps -Maximum).Maximum
        $tok = ($rs | Measure-Object -Property predicted_n -Average).Average
        # rule 11: acceptance AND mean draft length, from the server's own log
        $acc = 'n/a'; $len = 'n/a'
        $el = Join-Path $OUT ('srv-d2b-{0}.err.log' -f $tag)
        if (Test-Path $el) {
            $t = Get-Content -Raw $el
            $m = [regex]::Matches($t, 'n_accept\s*=\s*(\d+).*?n_draft\s*=\s*(\d+)')
            if ($m.Count) { $last = $m[$m.Count-1]; $a=[double]$last.Groups[1].Value; $d=[double]$last.Groups[2].Value; if ($d -gt 0) { $acc = [math]::Round($a/$d,4) } }
            $ml = [regex]::Matches($t, 'mean len\s*=\s*([\d.]+)')
            if ($ml.Count) { $len = $ml[$ml.Count-1].Groups[1].Value }
        }
        Write-Ledger $LED ('PAIR {0} | file={1} | GiB={2} | drafter={3} | decode_tps_mean={4:N2} | min={5:N2} | max={6:N2} | probes={7} | tokens_mean={8:N0} | acceptance={9} | mean_draft_len={10} | load_s={11}' -f `
            $tag, $f.tag, $f.gib, $s.tag, $tps, $mn, $mx, $rs.Count, $tok, $acc, $len, $srv.load_s)
    }
}
Write-Log 'DRAFTER-AT-2BIT DONE'
