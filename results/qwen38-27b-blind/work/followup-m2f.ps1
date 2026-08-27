# Follow-up M2f - does the wider draft tree recover the thinking-token loss?
#
# M2e found that at 91k depth the SAME server decodes reasoning tokens at
# 36.62 t/s and answer tokens at 62.02 t/s, with near-identical draft
# ACCEPTANCE (0.895 vs 0.907) but very different mean draft LENGTH
# (2.99 vs 4.31). Reading: with --spec-draft-p-min 0.75 the confidence gate
# truncates the draft tree on reasoning tokens; acceptance stays high precisely
# because the gate discards the uncertain part, so acceptance is blind to the
# loss. Prediction: a wider tree with a lower gate (n-max 10 / p-min 0.5, the
# M1 winner) should recover some of it on the thinking stream.
#
# One extra server load, thinking ON, same 1275-note prompt and depth as M2e,
# cooled-probe protocol. Compare against M2e's think-ON n4/p0.75 = 36.62 t/s.
# NB: do not name any variable $base - it collides case-insensitively with
# lib.ps1's $script:BASE and wedges Start-Srv's health poll.
$ErrorActionPreference = 'Continue'
. 'E:\AI\measured-inference\results\qwen38-27b-blind\work\lib.ps1'
$script:DATA = 'E:\AI\measured-inference\results\qwen38-27b-blind\data\followup'
$out = Join-Path $script:DATA 'm2f-thinking-spec-flags.txt'
if (-not (Test-Path $out)) { New-Item -ItemType File -Path $out | Out-Null }

function Get-Filler([int]$n, [int]$seed) {
    $ls = New-Object System.Collections.Generic.List[string]
    for ($i = 1; $i -le $n; $i++) {
        $frag = [Convert]::ToString(((($i + $seed) * 48271) % 1048573), 16)
        $ls.Add('Note ' + $i + ': subsystem alpha-' + ((($i + $seed) * 7) % 97) + ' reported latency ' + ((17 * $i) % 993) + ' ms on shard ' + ($i % 13) + ', retry budget ' + ((3 * $i) % 29) + ', digest fragment ' + $frag + ', remark: the threshold was crossed only when the moving median over window ' + ((5 * $i) % 47) + ' exceeded the rolling baseline by ' + ((11 * $i) % 83) + ' percent during the ' + ((13 * $i) % 31) + ' minute observation interval.')
    }
    return [string]::Join("`n", $ls)
}
function Acc { param($r)
    if ($r.draft_n -and [double]$r.draft_n -gt 0) { return [math]::Round([double]$r.draft_acc / [double]$r.draft_n, 4) }
    return 'n/a'
}

$prompt = "Session id m2d-ladder run 13.`n" + 'Read these operations notes, then do the task at the end.' + "`n" + (Get-Filler 1275 13) + "`nTASK: " + $script:CODE_PROBE

$srvArgs = @('-c','131072','-ngl','99','--parallel','1','--load-mode','mmap','-ctk','q8_0','-ctv','q8_0','--reasoning-preserve')

$arms = @(
    @{ tag='thinkON-n10-p0.5';  extra=@('--spec-type','draft-mtp','--spec-draft-n-max','10','--spec-draft-p-min','0.5') },
    @{ tag='thinkON-nospec';    extra=@('--spec-type','none') }
)

foreach ($a in $arms) {
    Write-Host ("=== {0}  {1} ===" -f $a.tag, (Get-Date -Format 'HH:mm:ss'))
    $s = Start-Srv -Extra ($srvArgs + $a.extra) -Tag ("m2f-" + $a.tag) -TimeoutSec 900
    if (-not $s) { Write-Row $out ("SUMMARY {0} LOAD-FAILED" -f $a.tag); continue }
    $r0 = Invoke-Probe -Text $prompt -MaxTokens 300
    Write-Row $out ("  PREFILLPROBE {0} depth_tok={1} prefill_s={2} decode_tps={3} accept={4}" -f `
        $a.tag, $r0.prompt_n, [math]::Round($r0.prompt_ms/1000,2), $r0.decode_tps, (Acc $r0))
    Write-Host '  cooling 30 s...'
    Start-Sleep -Seconds 30
    $vals = @()
    for ($k = 1; $k -le 3; $k++) {
        $r = Invoke-Probe -Text $prompt -MaxTokens 300
        $vals += [double]$r.decode_tps
        Write-Row $out ("  PROBE {0} k={1} decode_tps={2} accept={3} predicted_n={4} think_chars={5}" -f `
            $a.tag, $k, $r.decode_tps, (Acc $r), $r.predicted_n, $r.think.Length)
    }
    $sorted = $vals | Sort-Object
    $median = $sorted[[int]([math]::Floor($sorted.Count / 2))]
    $mean = ($vals | Measure-Object -Average).Average
    Write-Row $out ("SUMMARY {0} depth_tok={1} n={2} median_tps={3} mean_tps={4} min_tps={5} max_tps={6}" -f `
        $a.tag, $r0.prompt_n, $vals.Count, [math]::Round($median,2), [math]::Round($mean,2), `
        [math]::Round(($sorted | Select-Object -First 1),2), [math]::Round(($sorted | Select-Object -Last 1),2))
    $ml = (Select-String -Path $s.err -Pattern 'draft acceptance' | Select-Object -Last 1)
    if ($ml) { Write-Row $out ("  LOG {0}| {1}" -f $a.tag, $ml.Line.Trim()) }
    Stop-Srv
}
Stop-Srv
Write-Host 'M2F DONE'
