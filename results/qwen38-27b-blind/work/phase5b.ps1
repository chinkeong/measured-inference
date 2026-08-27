# Phase 5b - the table a Recipe 2 user actually needs, and which nothing else
# in this campaign measured: decode vs depth for the SHIPPED configuration
# (-c 131072, projector loaded, MTP n10/p0.5) on ANSWER tokens, not reasoning
# tokens. Phase 5 was n4/p0.75, projector off, reasoning tokens.
$ErrorActionPreference = 'Continue'
. 'E:\AI\measured-inference\results\qwen38-27b-blind\work\lib.ps1'
$out = Join-Path $script:DATA 'phase5b.txt'
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

$s = Start-Srv -Extra @('-c','131072','-ngl','99','--parallel','1','--load-mode','mmap','-ctk','q8_0','-ctv','q8_0',
    '--mmproj', $script:MMPROJ, '--image-min-tokens','1024',
    '--chat-template-kwargs','{\"enable_thinking\":false}',
    '--spec-type','draft-mtp','--spec-draft-n-max','10','--spec-draft-p-min','0.5') -Tag 'r2-depth' -TimeoutSec 600
if (-not $s) { Write-Row $out 'PHASE5B LOAD-FAILED'; exit 1 }
$v = Get-Vram
Write-Row $out ("CONFIG recipe2 ctx=131072 mmproj=on spec=n10/p0.5 thinking=off board={0} ded={1} shr={2}" -f $v.board_mib, $v.srv_ded_mib, $v.srv_shr_mib)
$seed = 0
foreach ($n in @(20, 420, 1275)) {
    $seed++
    if ($done -match ("^RESULT r2-depth$n ")) { Write-Host "skip $n"; continue }
    $nonce = "Session id " + ([guid]::NewGuid().ToString()) + " run " + $seed + ".`n"
    $prompt = $nonce + 'Read these operations notes, then do the task at the end.' + "`n" + (Get-Filler $n $seed) + "`nTASK: " + $script:CODE_PROBE
    $r = Invoke-Probe -Text $prompt -MaxTokens 400
    $acc = 'n/a'
    if ($r.draft_n -and [double]$r.draft_n -gt 0) { $acc = [math]::Round([double]$r.draft_acc / [double]$r.draft_n, 4) }
    Write-Row $out ("RESULT r2-depth{0} depth_tok={1} prefill_tps={2} prefill_s={3} decode_tps={4} accept={5} predicted_n={6} answer_chars={7} think_chars={8}" -f `
        $n, $r.prompt_n, $r.prefill_tps, [math]::Round($r.prompt_ms/1000,2), $r.decode_tps, $acc, $r.predicted_n, $r.text.Length, $r.think.Length)
}
Stop-Srv
Write-Host 'PHASE5B DONE'
