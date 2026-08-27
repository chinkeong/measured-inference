# Phase 4d - text-only (no projector) resident ceiling. The mmproj-on sweep put
# the last fully-resident step at 163,840. The projector measured 1,138 MiB
# = ~25.9k tokens of window, so a text-only server should stay resident past
# 190k. Do not ship a derived ceiling: measure it.
$ErrorActionPreference = 'Continue'
. 'E:\AI\measured-inference\results\qwen38-27b-blind\work\lib.ps1'
$out = Join-Path $script:DATA 'phase4d.txt'
if (-not (Test-Path $out)) { New-Item -ItemType File -Path $out | Out-Null }
$done = Get-Content $out -ErrorAction SilentlyContinue
$SHORT = 'Write a JavaScript function that reverses a linked list in place. Code only.'

# Arm 0: VERIFY THE SHIPPED RECIPE. The ceiling sweep ran at MTP n4/p0.75;
# the recipe ships n10/p0.5. Confirm the promoted config's own VRAM at the
# promoted context before printing it as a recipe.
if (-not ($done -match '^RESULT recipe-mm-c163840 ')) {
    Write-Host '=== recipe-mm-c163840 (shipped config, verified) ==='
    $s0 = Start-Srv -Extra @('-c','163840','-ngl','99','--parallel','1','--load-mode','mmap','-ctk','q8_0','-ctv','q8_0',
        '--mmproj', $script:MMPROJ, '--image-min-tokens','1024','--reasoning-preserve',
        '--spec-type','draft-mtp','--spec-draft-n-max','10','--spec-draft-p-min','0.5') -Tag 'recipe-mm' -TimeoutSec 600
    if (-not $s0) { Write-Row $out 'RESULT recipe-mm-c163840 LOAD-FAILED' } else {
        $v0 = Get-Vram
        $r0 = Invoke-Probe -Text $script:CODE_PROBE -MaxTokens 700
        $acc0 = 'n/a'
        if ($r0.draft_n -and [double]$r0.draft_n -gt 0) { $acc0 = [math]::Round([double]$r0.draft_acc / [double]$r0.draft_n, 4) }
        Write-Row $out ("RESULT recipe-mm-c163840 ctx=163840 decode_tps={0} accept={1} board_mib={2} srv_ded_mib={3} srv_shr_mib={4}" -f `
            $r0.decode_tps, $acc0, $v0.board_mib, $v0.srv_ded_mib, $v0.srv_shr_mib)
        Stop-Srv
    }
}

foreach ($ctx in @(180224, 196608, 212992)) {
    $tag = "nomm-c$ctx"
    if ($done -match ("^RESULT " + [regex]::Escape($tag) + " ")) { Write-Host "skip $tag"; continue }
    Write-Host "=== $tag ==="
    $s = Start-Srv -Extra @('-c', "$ctx", '-ngl','99','--parallel','1','--load-mode','mmap','-ctk','q8_0','-ctv','q8_0',
        '--spec-type','draft-mtp','--spec-draft-n-max','10','--spec-draft-p-min','0.5') -Tag $tag -TimeoutSec 600
    if (-not $s) { Write-Row $out ("RESULT {0} LOAD-FAILED" -f $tag); continue }
    $v = Get-Vram
    $r = Invoke-Probe -Text $SHORT -MaxTokens 200
    Write-Row $out ("RESULT {0} ctx={1} decode_tps={2} board_mib={3} srv_ded_mib={4} srv_shr_mib={5}" -f `
        $tag, $ctx, $r.decode_tps, $v.board_mib, $v.srv_ded_mib, $v.srv_shr_mib)
    Stop-Srv
}
Write-Host 'PHASE4D DONE'
