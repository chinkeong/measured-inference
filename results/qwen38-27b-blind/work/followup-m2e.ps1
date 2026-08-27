# Follow-up M2e - thinking ON vs OFF at 91k depth, everything else identical.
#
# M2d's cooled ladder (thinking OFF) reads ~1.8x the campaign's phase5 ladder
# (thinking ON, single post-prefill probe per depth). Post-prefill clock state
# explains part of the spread but not a factor of 1.8. The other stated
# difference is the token stream: phase5 timed REASONING tokens, M2d timed code.
# At shallow depth the campaign measured that difference as only ~4 %
# (phase3 mtp-n4-p0.75 80.99 thinking-on vs phase3d nothink-n4-p0.75 84.47).
# This isolates it AT DEPTH: same server flags as M2d, same 1275-note prompt,
# thinking ON, cooled-probe protocol. The only change from M2d's deepest row is
# --chat-template-kwargs.
$ErrorActionPreference = 'Continue'
. 'E:\AI\measured-inference\results\qwen38-27b-blind\work\lib.ps1'
$script:DATA = 'E:\AI\measured-inference\results\qwen38-27b-blind\data\followup'
$out = Join-Path $script:DATA 'm2e-thinking-on-at-depth.txt'
if (-not (Test-Path $out)) { New-Item -ItemType File -Path $out | Out-Null }

function Get-Filler([int]$n, [int]$seed) {
    $ls = New-Object System.Collections.Generic.List[string]
    for ($i = 1; $i -le $n; $i++) {
        $frag = [Convert]::ToString(((($i + $seed) * 48271) % 1048573), 16)
        $ls.Add('Note ' + $i + ': subsystem alpha-' + ((($i + $seed) * 7) % 97) + ' reported latency ' + ((17 * $i) % 993) + ' ms on shard ' + ($i % 13) + ', retry budget ' + ((3 * $i) % 29) + ', digest fragment ' + $frag + ', remark: the threshold was crossed only when the moving median over window ' + ((5 * $i) % 47) + ' exceeded the rolling baseline by ' + ((11 * $i) % 83) + ' percent during the ' + ((13 * $i) % 31) + ' minute observation interval.')
    }
    return [string]::Join("`n", $ls)
}
function Get-Gpu {
    $l = ''
    try { $l = ((nvidia-smi --query-gpu=temperature.gpu,clocks.sm,power.draw,utilization.gpu --format=csv,noheader,nounits) | Select-Object -First 1).Trim() } catch {}
    return ($l -replace '\s*,\s*', '/')
}
function Acc { param($r)
    if ($r.draft_n -and [double]$r.draft_n -gt 0) { return [math]::Round([double]$r.draft_acc / [double]$r.draft_n, 4) }
    return 'n/a'
}

# Same seed/notes as M2d's deepest row so the prompt text matches exactly.
$prompt = "Session id m2d-ladder run 13.`n" + 'Read these operations notes, then do the task at the end.' + "`n" + (Get-Filler 1275 13) + "`nTASK: " + $script:CODE_PROBE

$srvArgs = @('-c','131072','-ngl','99','--parallel','1','--load-mode','mmap','-ctk','q8_0','-ctv','q8_0',
          '--spec-type','draft-mtp','--spec-draft-n-max','4','--spec-draft-p-min','0.75')

# arm A: thinking ON (server default, as phase4c/phase5 ran it, plus the
#        --reasoning-preserve the recipes ship). arm B: thinking OFF (= M2d).
$arms = @(
    @{ tag='think-ON';  extra=@('--reasoning-preserve') },
    @{ tag='think-OFF'; extra=@('--chat-template-kwargs', '{\"enable_thinking\":false}') }
)

foreach ($a in $arms) {
    Write-Host ("=== {0}  {1} ===" -f $a.tag, (Get-Date -Format 'HH:mm:ss'))
    # NB: this variable must NOT be called $base. PowerShell variable names are
    # case-insensitive, so $base would silently overwrite lib.ps1's $script:BASE
    # (the server URL), and Start-Srv's health poll would then request
    # "-c 131072 ... /health" forever. Cost one wedged 10-minute run to find.
    $s = Start-Srv -Extra ($srvArgs + $a.extra) -Tag ("m2e-" + $a.tag) -TimeoutSec 900
    if (-not $s) { Write-Row $out ("SUMMARY {0} LOAD-FAILED" -f $a.tag); continue }
    $v0 = Get-Vram
    Write-Row $out ("  VRAM {0} at-load board={1} ded={2} shr={3}" -f $a.tag, $v0.board_mib, $v0.srv_ded_mib, $v0.srv_shr_mib)
    $r0 = Invoke-Probe -Text $prompt -MaxTokens 300
    Write-Row $out ("  PREFILLPROBE {0} depth_tok={1} prefill_tps={2} prefill_s={3} decode_tps={4} accept={5} think_chars={6} answer_chars={7} gpu_after={8}" -f `
        $a.tag, $r0.prompt_n, $r0.prefill_tps, [math]::Round($r0.prompt_ms/1000,2), $r0.decode_tps, (Acc $r0), $r0.think.Length, $r0.text.Length, (Get-Gpu))
    Write-Host '  cooling 30 s...'
    Start-Sleep -Seconds 30
    $vals = @()
    for ($k = 1; $k -le 3; $k++) {
        $g = Get-Gpu
        $r = Invoke-Probe -Text $prompt -MaxTokens 300
        $vals += [double]$r.decode_tps
        Write-Row $out ("  PROBE {0} k={1} decode_tps={2} accept={3} predicted_n={4} think_chars={5} answer_chars={6} gpu_before={7}" -f `
            $a.tag, $k, $r.decode_tps, (Acc $r), $r.predicted_n, $r.think.Length, $r.text.Length, $g)
    }
    $sorted = $vals | Sort-Object
    $median = $sorted[[int]([math]::Floor($sorted.Count / 2))]
    $mean = ($vals | Measure-Object -Average).Average
    Write-Row $out ("SUMMARY {0} depth_tok={1} n={2} median_tps={3} mean_tps={4} min_tps={5} max_tps={6} postprefill_tps={7}" -f `
        $a.tag, $r0.prompt_n, $vals.Count, [math]::Round($median,2), [math]::Round($mean,2), `
        [math]::Round(($sorted | Select-Object -First 1),2), [math]::Round(($sorted | Select-Object -Last 1),2), $r0.decode_tps)
    Stop-Srv
}
Stop-Srv
Write-Host 'M2E DONE'
