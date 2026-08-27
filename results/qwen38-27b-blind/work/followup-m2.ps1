# Follow-up M2 - projector-at-depth PAIRED probe.
#
# Settles the campaign's loose end: phase4c read 30.61 t/s at 90,885 tok WITH
# the projector, phase5 read 35.81 t/s at 92,679 tok WITHOUT it - but those came
# from different scripts, different depths, different filler seeds, and the
# drafter was on in both (so acceptance could move the number).
#
# This pair is clean:
#   * identical prompt text in both arms (same nonce, same 1275-note filler,
#     same seed) -> identical depth in tokens
#   * --spec-type none in both arms -> no drafter, no acceptance variance;
#     no-spec decode is content-independent (campaign phase3d: 41.46-42.17 t/s
#     across four content types, 0.8 % spread)
#   * every other flag byte-identical; the ONLY difference is --mmproj
#   * arms alternate A,B,A,B so any thermal/driver drift is balanced
#   * two decode samples per server load (the 2nd request re-uses the cached
#     prefix for prefill and decodes the same 400 greedy tokens at the same
#     depth)
# Speed numbers come from the server's own timings, never wall-clock.
$ErrorActionPreference = 'Continue'
. 'E:\AI\measured-inference\results\qwen38-27b-blind\work\lib.ps1'
$script:DATA = 'E:\AI\measured-inference\results\qwen38-27b-blind\data\followup'
$out = Join-Path $script:DATA 'm2-projector-depth.txt'
if (-not (Test-Path $out)) { New-Item -ItemType File -Path $out | Out-Null }
$done = Get-Content $out -ErrorAction SilentlyContinue

# Same filler generator as phase4c / phase5, so depth is comparable to them.
function Get-Filler([int]$n, [int]$seed) {
    $ls = New-Object System.Collections.Generic.List[string]
    for ($i = 1; $i -le $n; $i++) {
        $frag = [Convert]::ToString(((($i + $seed) * 48271) % 1048573), 16)
        $ls.Add('Note ' + $i + ': subsystem alpha-' + ((($i + $seed) * 7) % 97) + ' reported latency ' + ((17 * $i) % 993) + ' ms on shard ' + ($i % 13) + ', retry budget ' + ((3 * $i) % 29) + ', digest fragment ' + $frag + ', remark: the threshold was crossed only when the moving median over window ' + ((5 * $i) % 47) + ' exceeded the rolling baseline by ' + ((11 * $i) % 83) + ' percent during the ' + ((13 * $i) % 31) + ' minute observation interval.')
    }
    return [string]::Join("`n", $ls)
}

# 1275 notes with seed 3 reproduces phase4c's deepest row (90,885 tokens).
$NOTES = 1275
$SEED  = 3
$nonce = "Session id followup-m2-fixed-nonce run 1.`n"
$PROMPT = $nonce + 'Read these operations notes, then do the task at the end.' + "`n" + (Get-Filler $NOTES $SEED) + "`nTASK: " + $script:CODE_PROBE

$common  = @('-c','131072','-ngl','99','--parallel','1','--load-mode','mmap','-ctk','q8_0','-ctv','q8_0','--spec-type','none')
$NOTHINK = @('--chat-template-kwargs', '{\"enable_thinking\":false}')
$WITH    = @('--mmproj', $script:MMPROJ, '--image-min-tokens','1024')

# A = projector loaded, B = no projector. Alternating replicates.
$plan = @(
    @{ arm='WITH-mmproj'; rep=1; extra=$WITH },
    @{ arm='NO-mmproj';   rep=1; extra=@() },
    @{ arm='WITH-mmproj'; rep=2; extra=$WITH },
    @{ arm='NO-mmproj';   rep=2; extra=@() }
)

foreach ($p in $plan) {
    $row = "$($p.arm)/rep$($p.rep)"
    if ($done -match ("^RESULT " + [regex]::Escape($row) + " ")) { Write-Host "skip $row"; continue }
    Write-Host ("=== {0}  {1} ===" -f $row, (Get-Date -Format 'HH:mm:ss'))
    $s = Start-Srv -Extra ($common + $NOTHINK + $p.extra) -Tag ("m2-" + ($row -replace '[\\/]','-')) -TimeoutSec 900
    if (-not $s) { Write-Row $out ("RESULT {0} LOAD-FAILED" -f $row); continue }
    $v0 = Get-Vram
    Write-Row $out ("  VRAM {0} at-load board={1} ded={2} shr={3} load_s={4}" -f $row, $v0.board_mib, $v0.srv_ded_mib, $v0.srv_shr_mib, $s.load_s)
    $r1 = Invoke-Probe -Text $PROMPT -MaxTokens 400
    $r2 = Invoke-Probe -Text $PROMPT -MaxTokens 400
    $v1 = Get-Vram
    Write-Row $out ("RESULT {0} depth_tok={1} prefill_tps={2} prefill_s={3} decode_tps_1={4} decode_tps_2={5} predicted_n_1={6} predicted_n_2={7} answer_chars={8} think_chars={9} finish={10} board_mib={11} ded_mib={12} shr_mib={13}" -f `
        $row, $r1.prompt_n, $r1.prefill_tps, [math]::Round($r1.prompt_ms/1000,2), $r1.decode_tps, $r2.decode_tps, `
        $r1.predicted_n, $r2.predicted_n, $r1.text.Length, $r1.think.Length, $r1.finish, `
        $v1.board_mib, $v1.srv_ded_mib, $v1.srv_shr_mib)
    Stop-Srv
}
Stop-Srv
Write-Host 'M2 DONE'
