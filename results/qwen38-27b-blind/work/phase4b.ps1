# Phase 4b - isolate the per-token KV slope WITHOUT the MTP draft context.
# The mmproj-on, MTP-on sweep shows 1408 MiB of dedicated VRAM per 32,768
# tokens = 45,056 B/token, well above the 34,816 B/token the config.json
# arithmetic predicts for a q8_0 cache. Two loads with --spec-type none at the
# same two contexts give the main cache's slope on its own; the difference is
# what speculation costs per token of window.
$ErrorActionPreference = 'Continue'
. 'E:\AI\measured-inference\results\qwen38-27b-blind\work\lib.ps1'
$out = Join-Path $script:DATA 'phase4b.txt'
if (-not (Test-Path $out)) { New-Item -ItemType File -Path $out | Out-Null }
$done = Get-Content $out -ErrorAction SilentlyContinue
$SHORT = 'Write a JavaScript function that reverses a linked list in place. Code only.'

$arms = @(
    @{ tag='nospec-c32768';  ctx=32768;  extra=@('--spec-type','none') },
    @{ tag='nospec-c163840'; ctx=163840; extra=@('--spec-type','none') }
)
foreach ($a in $arms) {
    if ($done -match ("^RESULT " + [regex]::Escape($a.tag) + " ")) { Write-Host "skip $($a.tag)"; continue }
    Write-Host "=== $($a.tag) ==="
    $extra = @('-c', "$($a.ctx)", '-ngl','99','--parallel','1','--load-mode','mmap','-ctk','q8_0','-ctv','q8_0',
               '--mmproj', $script:MMPROJ, '--image-min-tokens','1024') + $a.extra
    $s = Start-Srv -Extra $extra -Tag $a.tag -TimeoutSec 600
    if (-not $s) { Write-Row $out ("RESULT {0} LOAD-FAILED" -f $a.tag); continue }
    $v = Get-Vram
    $r = Invoke-Probe -Text $SHORT -MaxTokens 200
    Write-Row $out ("RESULT {0} ctx={1} decode_tps={2} board_mib={3} srv_ded_mib={4} srv_shr_mib={5}" -f `
        $a.tag, $a.ctx, $r.decode_tps, $v.board_mib, $v.srv_ded_mib, $v.srv_shr_mib)
    Stop-Srv
}
Write-Host 'PHASE4B DONE'
