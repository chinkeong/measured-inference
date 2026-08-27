# Phase 4c - the collapse point. The shallow ceiling sweep shows -c 262144
# loading and decoding at ~59 t/s with 3.5 GiB of the allocation living in
# SHARED (system RAM) memory. That is the "shallow-safe" ceiling and it is a
# trap: shallow probes never touch the spilled pages. This runs the SAME deep
# prompts on a fully-resident window (-c 131072) and on the overcommitted one
# (-c 262144) and compares decode.
$ErrorActionPreference = 'Continue'
. 'E:\AI\measured-inference\results\qwen38-27b-blind\work\lib.ps1'
$out = Join-Path $script:DATA 'phase4c.txt'
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

foreach ($ctx in @(131072, 262144)) {
    if ($done -match ("^RESULT c$ctx-deep1275 ")) { Write-Host "skip ctx $ctx"; continue }
    Write-Host "=== collapse probe at -c $ctx ==="
    $s = Start-Srv -Extra @('-c', "$ctx", '-ngl','99','--parallel','1','--load-mode','mmap','-ctk','q8_0','-ctv','q8_0',
        '--mmproj', $script:MMPROJ, '--image-min-tokens','1024',
        '--spec-type','draft-mtp','--spec-draft-n-max','4','--spec-draft-p-min','0.75') -Tag "deep-c$ctx" -TimeoutSec 600
    if (-not $s) { Write-Row $out ("RESULT c$ctx LOAD-FAILED"); continue }
    $v0 = Get-Vram
    Write-Row $out ("VRAM c{0} at-load board={1} ded={2} shr={3}" -f $ctx, $v0.board_mib, $v0.srv_ded_mib, $v0.srv_shr_mib)
    $seed = 0
    foreach ($n in @(20, 420, 1275)) {
        $seed++
        $nonce = "Session id " + ([guid]::NewGuid().ToString()) + " run " + $seed + ".`n"
        $prompt = $nonce + 'Read these operations notes, then do the task at the end.' + "`n" + (Get-Filler $n $seed) + "`nTASK: " + $script:CODE_PROBE
        $r = Invoke-Probe -Text $prompt -MaxTokens 300
        $v = Get-Vram
        $acc = 'n/a'
        if ($r.draft_n -and [double]$r.draft_n -gt 0) { $acc = [math]::Round([double]$r.draft_acc / [double]$r.draft_n, 4) }
        Write-Row $out ("RESULT c{0}-deep{1} ctx={0} depth_tok={2} prefill_tps={3} decode_tps={4} accept={5} predicted_n={6} board={7} ded={8} shr={9}" -f `
            $ctx, $n, $r.prompt_n, $r.prefill_tps, $r.decode_tps, $acc, $r.predicted_n, $v.board_mib, $v.srv_ded_mib, $v.srv_shr_mib)
    }
    Stop-Srv
}
Write-Host 'PHASE4C DONE'
