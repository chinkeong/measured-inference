# Follow-up M2d - depth ladder re-measured with the cooled-probe protocol.
#
# Cross-check for M2/M2b/M2c. The campaign's depth series (phase5: 51.15 t/s at
# 1,533 tok falling to 35.81 at 92,679; phase4c: 53.48 -> 30.61 at 90,885) are
# each built from ONE probe per depth, fired immediately after that depth's
# prefill. M2b showed that such a probe varies 18.27-26.60 t/s on a FIXED
# configuration depending on the card's clock state. This re-runs the ladder
# with the protocol that removed that variance, in a SINGLE server load so
# every depth shares one set of load-time flags.
#
# Config: UD-IQ4_XS, -c 131072, -ngl 99, --parallel 1, --load-mode mmap,
# -ctk q8_0 -ctv q8_0, --spec-type draft-mtp --spec-draft-n-max 4
# --spec-draft-p-min 0.75, no projector, thinking off, temp 0 / top_k 1,
# max_tokens 400. Per depth: prefill probe discarded, 30 s cooldown, 3 probes.
$ErrorActionPreference = 'Continue'
. 'E:\AI\measured-inference\results\qwen38-27b-blind\work\lib.ps1'
$script:DATA = 'E:\AI\measured-inference\results\qwen38-27b-blind\data\followup'
$out = Join-Path $script:DATA 'm2d-depth-ladder-cooled.txt'
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

$extra = @('-c','131072','-ngl','99','--parallel','1','--load-mode','mmap','-ctk','q8_0','-ctv','q8_0',
           '--spec-type','draft-mtp','--spec-draft-n-max','4','--spec-draft-p-min','0.75',
           '--chat-template-kwargs', '{\"enable_thinking\":false}')
$s = Start-Srv -Extra $extra -Tag 'm2d-depth-ladder' -TimeoutSec 900
if (-not $s) { Write-Row $out 'M2D LOAD-FAILED'; exit 1 }
$v0 = Get-Vram
Write-Row $out ("CONFIG m2d ctx=131072 spec=n4/p0.75 mmproj=off thinking=off board={0} ded={1} shr={2}" -f $v0.board_mib, $v0.srv_ded_mib, $v0.srv_shr_mib)

$seed = 10
foreach ($n in @(20, 400, 1275)) {
    $seed++
    $prompt = "Session id m2d-ladder run $seed.`n" + 'Read these operations notes, then do the task at the end.' + "`n" + (Get-Filler $n $seed) + "`nTASK: " + $script:CODE_PROBE
    $r0 = Invoke-Probe -Text $prompt -MaxTokens 400
    Write-Row $out ("  PREFILLPROBE notes={0} depth_tok={1} prefill_tps={2} prefill_s={3} decode_tps={4} accept={5} gpu_after={6}" -f `
        $n, $r0.prompt_n, $r0.prefill_tps, [math]::Round($r0.prompt_ms/1000,2), $r0.decode_tps, (Acc $r0), (Get-Gpu))
    Write-Host "  cooling 30 s (notes=$n)..."
    Start-Sleep -Seconds 30
    $vals = @()
    for ($k = 1; $k -le 3; $k++) {
        $g = Get-Gpu
        $r = Invoke-Probe -Text $prompt -MaxTokens 400
        $vals += [double]$r.decode_tps
        Write-Row $out ("  PROBE notes={0} k={1} decode_tps={2} accept={3} gpu_before={4}" -f $n, $k, $r.decode_tps, (Acc $r), $g)
    }
    $sorted = $vals | Sort-Object
    $median = $sorted[[int]([math]::Floor($sorted.Count / 2))]
    $mean = ($vals | Measure-Object -Average).Average
    Write-Row $out ("RESULT notes={0} depth_tok={1} prefill_tps={2} median_tps={3} mean_tps={4} min_tps={5} max_tps={6} postprefill_tps={7}" -f `
        $n, $r0.prompt_n, $r0.prefill_tps, [math]::Round($median,2), [math]::Round($mean,2), `
        [math]::Round(($sorted | Select-Object -First 1),2), [math]::Round(($sorted | Select-Object -Last 1),2), $r0.decode_tps)
}
$v1 = Get-Vram
Write-Row $out ("VRAM_AT_END board={0} ded={1} shr={2}" -f $v1.board_mib, $v1.srv_ded_mib, $v1.srv_shr_mib)
Stop-Srv
Write-Host 'M2D DONE'
