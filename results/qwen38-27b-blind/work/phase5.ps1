# Phase 5 - depth series. One server, probes at increasing prompt depth.
# Each prompt carries a unique nonce FIRST so llama.cpp's prefix cache cannot
# reuse anything: prompt_n / prompt_ms then describe the whole prefill.
# Speed numbers come from the server's timings, never wall-clock.
$ErrorActionPreference = 'Continue'
. 'E:\AI\measured-inference\results\qwen38-27b-blind\work\lib.ps1'
$out = Join-Path $script:DATA 'phase5.txt'
if (-not (Test-Path $out)) { New-Item -ItemType File -Path $out | Out-Null }
$done = Get-Content $out -ErrorAction SilentlyContinue

$SPEC = @('--spec-type','draft-mtp','--spec-draft-n-max','4','--spec-draft-p-min','0.75')
if ($env:PH5_SPEC) { $SPEC = $env:PH5_SPEC -split ' ' }
$CTX = 131072
if ($env:PH5_CTX) { $CTX = [int]$env:PH5_CTX }

function Get-Filler([int]$n, [int]$seed) {
    $ls = New-Object System.Collections.Generic.List[string]
    for ($i = 1; $i -le $n; $i++) {
        $frag = [Convert]::ToString(((($i + $seed) * 48271) % 1048573), 16)
        $ls.Add('Note ' + $i + ': subsystem alpha-' + ((($i + $seed) * 7) % 97) + ' reported latency ' + ((17 * $i) % 993) + ' ms on shard ' + ($i % 13) + ', retry budget ' + ((3 * $i) % 29) + ', digest fragment ' + $frag + ', remark: the threshold was crossed only when the moving median over window ' + ((5 * $i) % 47) + ' exceeded the rolling baseline by ' + ((11 * $i) % 83) + ' percent during the ' + ((13 * $i) % 31) + ' minute observation interval.')
    }
    return [string]::Join("`n", $ls)
}

$s = Start-Srv -Extra (@('-c', "$CTX", '-ngl','99','--parallel','1','--load-mode','mmap','-ctk','q8_0','-ctv','q8_0') + $SPEC) -Tag 'depth' -TimeoutSec 600
if (-not $s) { Write-Row $out 'PHASE5 LOAD-FAILED'; exit 1 }
Write-Row $out ("CONFIG ctx={0} spec={1}" -f $CTX, ($SPEC -join ' '))

$notes = @(20, 150, 400, 800, 1300)
$seed = 0
foreach ($n in $notes) {
    $seed++
    if ($done -match ("^RESULT depth-notes$n ")) { Write-Host "skip notes=$n"; continue }
    $nonce = "Session id " + ([guid]::NewGuid().ToString()) + " run " + $seed + ".`n"
    $prompt = $nonce + 'Read these operations notes, then do the task at the end.' + "`n" + (Get-Filler $n $seed) + "`nTASK: " + $script:CODE_PROBE
    $r = Invoke-Probe -Text $prompt -MaxTokens 300
    $acc = 'n/a'
    if ($r.draft_n -and [double]$r.draft_n -gt 0) { $acc = [math]::Round([double]$r.draft_acc / [double]$r.draft_n, 4) }
    Write-Row $out ("RESULT depth-notes{0} depth_tok={1} prefill_tps={2} prefill_s={3} decode_tps={4} predicted_n={5} accept={6} wall_s={7}" -f `
        $n, $r.prompt_n, $r.prefill_tps, [math]::Round($r.prompt_ms/1000,2), $r.decode_tps, $r.predicted_n, $acc, $r.wall_s)
}
$v = Get-Vram
Write-Row $out ("VRAM_AT_END board_mib={0} srv_ded_mib={1} srv_shr_mib={2}" -f $v.board_mib, $v.srv_ded_mib, $v.srv_shr_mib)
Stop-Srv
Write-Host 'PHASE5 DONE'
