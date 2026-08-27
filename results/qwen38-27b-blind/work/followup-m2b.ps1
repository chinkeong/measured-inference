# Follow-up M2b - projector-at-depth paired probe, NOISE-CONTROLLED rerun.
#
# M2 (ABAB, 2 decode samples per load) came back with 5-40 % spread INSIDE each
# arm, which is bigger than the effect being tested. The pattern - the probe
# fired immediately after the 105 s, 350 W prefill was always the slowest of its
# load - points at GPU clock/thermal state, not at the projector. This rerun
# controls for it:
#   * the post-prefill probe is recorded but EXCLUDED from the arm statistic
#   * a 45 s cooldown after prefill puts every measured probe in the same
#     thermal state
#   * 5 measured probes per load instead of 1
#   * ABBA ordering (WITH, NO, NO, WITH) cancels linear drift across the run
#   * nvidia-smi temp / SM clock / power sampled immediately before each probe
# Everything else is byte-identical to M2: same 90,862-token prompt, -c 131072,
# -ngl 99, --parallel 1, --load-mode mmap, -ctk q8_0 -ctv q8_0, --spec-type none
# (no drafter -> no acceptance variance), thinking off, temp 0 / top_k 1,
# max_tokens 400. The ONLY difference between arms is --mmproj.
$ErrorActionPreference = 'Continue'
. 'E:\AI\measured-inference\results\qwen38-27b-blind\work\lib.ps1'
$script:DATA = 'E:\AI\measured-inference\results\qwen38-27b-blind\data\followup'
$out = Join-Path $script:DATA 'm2b-projector-depth.txt'
if (-not (Test-Path $out)) { New-Item -ItemType File -Path $out | Out-Null }
$done = Get-Content $out -ErrorAction SilentlyContinue

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

$NOTES = 1275
$SEED  = 3
$nonce = "Session id followup-m2-fixed-nonce run 1.`n"
$PROMPT = $nonce + 'Read these operations notes, then do the task at the end.' + "`n" + (Get-Filler $NOTES $SEED) + "`nTASK: " + $script:CODE_PROBE

$common  = @('-c','131072','-ngl','99','--parallel','1','--load-mode','mmap','-ctk','q8_0','-ctv','q8_0','--spec-type','none')
$NOTHINK = @('--chat-template-kwargs', '{\"enable_thinking\":false}')
$WITH    = @('--mmproj', $script:MMPROJ, '--image-min-tokens','1024')

$plan = @(
    @{ arm='WITH-mmproj'; rep=3; extra=$WITH },
    @{ arm='NO-mmproj';   rep=3; extra=@() },
    @{ arm='NO-mmproj';   rep=4; extra=@() },
    @{ arm='WITH-mmproj'; rep=4; extra=$WITH }
)

foreach ($p in $plan) {
    $row = "$($p.arm)/rep$($p.rep)"
    if ($done -match ("^SUMMARY " + [regex]::Escape($row) + " ")) { Write-Host "skip $row"; continue }
    Write-Host ("=== {0}  {1} ===" -f $row, (Get-Date -Format 'HH:mm:ss'))
    $s = Start-Srv -Extra ($common + $NOTHINK + $p.extra) -Tag ("m2b-" + ($row -replace '[\\/]','-')) -TimeoutSec 900
    if (-not $s) { Write-Row $out ("SUMMARY {0} LOAD-FAILED" -f $row); continue }
    $v0 = Get-Vram
    Write-Row $out ("  VRAM {0} at-load board={1} ded={2} shr={3} load_s={4}" -f $row, $v0.board_mib, $v0.srv_ded_mib, $v0.srv_shr_mib, $s.load_s)

    # Probe 0: pays the full prefill. Recorded, excluded from the statistic.
    $g0 = Get-Gpu
    $r0 = Invoke-Probe -Text $PROMPT -MaxTokens 400
    Write-Row $out ("  PREFILLPROBE {0} depth_tok={1} prefill_tps={2} prefill_s={3} decode_tps={4} gpu_before={5} gpu_after={6}" -f `
        $row, $r0.prompt_n, $r0.prefill_tps, [math]::Round($r0.prompt_ms/1000,2), $r0.decode_tps, $g0, (Get-Gpu))

    Write-Host '  cooling 45 s...'
    Start-Sleep -Seconds 45

    $vals = @()
    for ($k = 1; $k -le 5; $k++) {
        $g = Get-Gpu
        $r = Invoke-Probe -Text $PROMPT -MaxTokens 400
        $vals += [double]$r.decode_tps
        Write-Row $out ("  PROBE {0} k={1} decode_tps={2} predicted_n={3} prefill_s={4} gpu_before={5}" -f `
            $row, $k, $r.decode_tps, $r.predicted_n, [math]::Round($r.prompt_ms/1000,2), $g)
    }
    $sorted = $vals | Sort-Object
    $median = $sorted[[int]([math]::Floor($sorted.Count / 2))]
    $mean = ($vals | Measure-Object -Average).Average
    $v1 = Get-Vram
    Write-Row $out ("SUMMARY {0} depth_tok={1} n={2} median_tps={3} mean_tps={4} min_tps={5} max_tps={6} board_mib={7} ded_mib={8} shr_mib={9}" -f `
        $row, $r0.prompt_n, $vals.Count, [math]::Round($median,2), [math]::Round($mean,2), `
        [math]::Round(($sorted | Select-Object -First 1),2), [math]::Round(($sorted | Select-Object -Last 1),2), `
        $v1.board_mib, $v1.srv_ded_mib, $v1.srv_shr_mib)
    Stop-Srv
}
Stop-Srv
Write-Host 'M2B DONE'
