# parallel-drafter-pair.ps1 - negative-register entry 9, closed.
#
# THE OPEN ITEM: section 06.06 measured --parallel 2 against --parallel 1 with
# the drafter OFF and got +60.3% aggregate throughput and -39.6% J/token. A
# prior campaign measured roughly +11% with the drafter ON. Neither ships as
# guidance because the pair is unmatched: drafting already amortises the weight
# read that batching also amortises, so the two mechanisms may not add.
#
# THIS CLOSES IT by measuring the SAME two arms with the drafter ON, at the
# flags the recipes ship - which is rule 25's new "sweep at the shipped recipe"
# clause applied to the thing that earned it last night.
#
# Aggregate throughput for --parallel 2 is the sum across concurrent slots, so
# the two requests are issued together and the aggregate is (total tokens) /
# (wall time of the slower one). Rule 12: discard the first post-prefill probe.
param([int]$DeadlineMinutes = 60, [int]$MaxVramMiB = 2000)
$ErrorActionPreference = 'Continue'
. 'E:\AI\measured-inference\scripts\quant-ladder\ladder-lib.ps1'

$MODEL = 'C:\Users\chink\.lmstudio\models\unsloth\Qwen3.8-27B-GGUF\Qwen3.8-27B-UD-IQ4_XS.gguf'
$DATA  = 'E:\AI\measured-inference\results\qwen38-27b-blind\data\quant-ladder'
$OUT   = Join-Path $DATA 'parallel-pair'
if (-not (Test-Path $OUT)) { New-Item -ItemType Directory -Path $OUT -Force | Out-Null }
$LED = Join-Path $OUT 'parallel-pair.txt'
if (-not (Test-Path $LED)) {
    Set-Content -LiteralPath $LED -Encoding utf8 -Value ('# entry 9 - matched drafter-ON --parallel pair - opened {0}' -f (Get-Date -Format 's'))
}
$PORT = 1235
$DEADLINE = (Get-Date).AddMinutes($DeadlineMinutes)

$PROMPT = @'
Write a single self-contained JavaScript module that implements a fixed-window
rate limiter with a pluggable clock, a per-key limit, and an eviction sweep that
runs at most once per window. Include JSDoc on every exported symbol and a short
usage example at the end. Do not explain the code outside the module.
'@

while ((Get-Date) -lt $DEADLINE) {
    $procs = @(Get-Process -Name 'llama-server','llama-perplexity','llama-cli','llama-bench' -ErrorAction SilentlyContinue).Count
    $v = 999999; try { $v = [int](& nvidia-smi --query-gpu=memory.used --format=csv,noheader,nounits | Select-Object -First 1) } catch {}
    if ($procs -eq 0 -and $v -lt $MaxVramMiB) { break }
    Write-Log ('waiting for the card - procs={0} vram={1}' -f $procs, $v); Start-Sleep -Seconds 45
}

foreach ($par in @(1, 2)) {
    if ((Get-Date) -ge $DEADLINE) { break }
    $tag = 'par' + $par
    if (Test-LedgerHas $LED ('PAR ' + $tag + ' ')) { Write-Log ('skip ' + $tag); continue }
    $flags = @('-ngl','99','-c','32768','-fa','on','--parallel',"$par",
               '-ctk','q8_0','-ctv','q8_0','--jinja','--reasoning','off',
               '--spec-type','draft-mtp','--spec-draft-n-max','10','--spec-draft-p-min','0.5')
    $srv = Start-Srv -ModelPath $MODEL -Tag ('pp-' + $tag) -Flags $flags -Port $PORT -LogDir $OUT
    if (-not $srv) { Write-Ledger $LED ('PAR {0} | SRVFAIL' -f $tag); continue }
    $null = Invoke-Probe -Text $PROMPT -MaxTokens 700 -Port $PORT -TimeoutSec 600   # rule 12
    Start-Sleep -Seconds 4

    $agg = @()
    for ($rep = 0; $rep -lt 3; $rep++) {
        $sw = [Diagnostics.Stopwatch]::StartNew()
        if ($par -eq 1) {
            $r = Invoke-Probe -Text $PROMPT -MaxTokens 700 -Port $PORT -TimeoutSec 600
            $sw.Stop()
            if ($r.ok) { $agg += [pscustomobject]@{ tokens = $r.predicted_n; wall = $sw.Elapsed.TotalSeconds; per_slot = $r.decode_tps } }
        } else {
            # two concurrent requests: aggregate = total tokens / wall of the slower
            $jobs = 1..2 | ForEach-Object {
                Start-Job -ScriptBlock {
                    param($p, $port)
                    $body = @{ model='pp'; temperature=0; top_k=1; max_tokens=700; messages=@(@{role='user';content=$p}) } | ConvertTo-Json -Depth 6
                    $resp = Invoke-RestMethod -Uri ("http://127.0.0.1:$port/v1/chat/completions") -Method Post -Body $body -ContentType 'application/json' -TimeoutSec 600
                    [pscustomobject]@{ n = $resp.timings.predicted_n; tps = $resp.timings.predicted_per_second }
                } -ArgumentList $PROMPT, $PORT
            }
            $res = $jobs | Wait-Job -Timeout 600 | Receive-Job
            $jobs | Remove-Job -Force -ErrorAction SilentlyContinue
            $sw.Stop()
            if ($res -and $res.Count -eq 2) {
                $tot = ($res | Measure-Object -Property n -Sum).Sum
                $agg += [pscustomobject]@{ tokens = $tot; wall = $sw.Elapsed.TotalSeconds; per_slot = (($res | Measure-Object -Property tps -Average).Average) }
            }
        }
        Start-Sleep -Seconds 3
    }
    Stop-Srv
    if (-not $agg.Count) { Write-Ledger $LED ('PAR {0} | NOPROBE' -f $tag); continue }
    $aggTps = ($agg | ForEach-Object { $_.tokens / $_.wall } | Measure-Object -Average).Average
    $slot   = ($agg | Measure-Object -Property per_slot -Average).Average
    $len = 'n/a'; $acc = 'n/a'
    $el = Join-Path $OUT ('srv-pp-{0}.err.log' -f $tag)
    if (Test-Path $el) {
        $t = Get-Content -Raw $el
        $m = [regex]::Matches($t, 'draft acceptance = ([\d.]+)')
        if ($m.Count) { $acc = $m[$m.Count-1].Groups[1].Value }
        $ml = [regex]::Matches($t, 'mean len =\s*([\d.]+)')
        if ($ml.Count) { $len = $ml[$ml.Count-1].Groups[1].Value }
    }
    Write-Ledger $LED ('PAR {0} | parallel={1} | drafter=ON n10/p0.5 | aggregate_tps={2:N2} | per_slot_tps={3:N2} | reps={4} | acceptance={5} | mean_draft_len={6}' -f `
        $tag, $par, $aggTps, $slot, $agg.Count, $acc, $len)
}
Write-Log 'PARALLEL-PAIR DONE'
