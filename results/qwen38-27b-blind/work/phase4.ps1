# Phase 4 — memory: context ceiling sweep with VRAM readings.
# Two ceilings are being separated:
#   fully-resident : largest -c where llama-server's SHARED (system-RAM) GPU
#                    usage stays ~0 — the whole window lives in dedicated VRAM
#   shallow-safe   : largest -c that still loads and decodes fast on a SHALLOW
#                    prompt even though the board is overcommitted
#   collapse       : first -c that fails to load, or whose shallow probe falls
#                    off a cliff
# mmproj is ON for the main sweep (the harder, honest case). One no-mmproj arm
# at the top measures the projector's cost in tokens of window.
$ErrorActionPreference = 'Continue'
. 'E:\AI\measured-inference\results\qwen38-27b-blind\work\lib.ps1'
$out = Join-Path $script:DATA 'phase4.txt'
if (-not (Test-Path $out)) { New-Item -ItemType File -Path $out | Out-Null }
$done = Get-Content $out -ErrorAction SilentlyContinue

$SPEC = @('--spec-type','draft-mtp','--spec-draft-n-max','4','--spec-draft-p-min','0.75')
if ($env:PH4_SPEC) { $SPEC = $env:PH4_SPEC -split ' ' }
$SHORT = 'Write a JavaScript function that reverses a linked list in place. Code only.'

function Try-Ctx {
    param([int]$Ctx, [bool]$WithMmproj = $true)
    $tag = "c$Ctx" + $(if ($WithMmproj) { '-mm' } else { '-nomm' })
    $extra = @('-c', "$Ctx", '-ngl','99','--parallel','1','--load-mode','mmap','-ctk','q8_0','-ctv','q8_0') + $SPEC
    if ($WithMmproj) { $extra += @('--mmproj', $script:MMPROJ, '--image-min-tokens','1024') }
    $s = Start-Srv -Extra $extra -Tag $tag -TimeoutSec 600
    if (-not $s) { Write-Row $script:OUTF ("RESULT {0} LOAD-FAILED" -f $tag); return -1 }
    $v = Get-Vram
    $r = Invoke-Probe -Text $SHORT -MaxTokens 200
    $v2 = Get-Vram
    $kv = ''
    foreach ($f in @($s.err, $s.out)) {
        if (Test-Path $f) { $m = Select-String -Path $f -Pattern 'KV self size|KV buffer size' | Select-Object -First 2; if ($m) { $kv = (($m | ForEach-Object { $_.Line.Trim() }) -join ' ;; ') } }
    }
    Write-Row $script:OUTF ("RESULT {0} ctx={1} mmproj={2} load_s={3} decode_tps={4} prefill_tps={5} board_mib={6} srv_ded_mib={7} srv_shr_mib={8} board_after={9} shr_after={10} kv=[{11}]" -f `
        $tag, $Ctx, $WithMmproj, $s.load_s, $r.decode_tps, $r.prefill_tps, $v.board_mib, $v.srv_ded_mib, $v.srv_shr_mib, $v2.board_mib, $v2.srv_shr_mib, $kv)
    Stop-Srv
    return [double]$r.decode_tps
}
$script:OUTF = $out

$steps = @(32768, 65536, 98304, 131072, 163840, 196608, 229376, 262144)
$results = @{}
foreach ($c in $steps) {
    $tag = "c$c-mm"
    if ($done -match ("^RESULT " + [regex]::Escape($tag) + " ")) { Write-Host "skip $tag"; continue }
    Write-Host "=== ctx $c (mmproj on) ==="
    $t = Try-Ctx -Ctx $c -WithMmproj $true
    $results[$c] = $t
    if ($t -lt 0) { Write-Host "load failed at $c - stopping upward sweep"; break }
}

# no-mmproj arm at native max, to price the projector
if (-not ($done -match '^RESULT c262144-nomm ')) {
    Write-Host '=== ctx 262144 (mmproj OFF) ==='
    Try-Ctx -Ctx 262144 -WithMmproj $false | Out-Null
}
Write-Host 'PHASE4 DONE'
