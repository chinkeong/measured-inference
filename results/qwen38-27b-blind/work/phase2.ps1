# Phase 2 â€” foundation & sanity.
#  A) -ngl 99, q8_0 KV, spec none  -> the decode FLOOR + server-reported KV size
#  B) -ngl 99, f16  KV, spec none  -> f16 KV size for the arithmetic check
#  C) -ngl 64,  q8_0 KV, spec none -> the -ngl off-by-one trap, measured
# Resumable: skips any arm whose result line is already in the out file.
$ErrorActionPreference = 'Continue'
. 'E:\AI\measured-inference\results\qwen38-27b-blind\work\lib.ps1'
$out = Join-Path $script:DATA 'phase2.txt'
if (-not (Test-Path $out)) { New-Item -ItemType File -Path $out | Out-Null }
$done = Get-Content $out -ErrorAction SilentlyContinue

$idle = Get-Vram
Write-Row $out ("IDLE board_vram_mib={0}  (desktop overhead, no server)" -f $idle.board_mib)

$arms = @(
    @{ tag = 'A-ngl99-q8';  extra = @('-c','32768','-ngl','99','--parallel','1','--load-mode','mmap','-ctk','q8_0','-ctv','q8_0','--spec-type','none') },
    @{ tag = 'B-ngl99-f16'; extra = @('-c','32768','-ngl','99','--parallel','1','--load-mode','mmap','-ctk','f16','-ctv','f16','--spec-type','none') },
    @{ tag = 'C-ngl64-q8';  extra = @('-c','32768','-ngl','64','--parallel','1','--load-mode','mmap','-ctk','q8_0','-ctv','q8_0','--spec-type','none') }
)
foreach ($arm in $arms) {
    if ($done -match ("^RESULT " + $arm.tag)) { Write-Host "skip $($arm.tag) (done)"; continue }
    Write-Host "=== $($arm.tag) ==="
    $s = Start-Srv -Extra $arm.extra -Tag $arm.tag
    if (-not $s) { Write-Row $out ("RESULT {0} LOAD-FAILED" -f $arm.tag); continue }
    $v = Get-Vram
    $r = Invoke-Probe -Text $script:CODE_PROBE -MaxTokens 700
    $cpu = 0
    try { $cpu = [math]::Round(((Get-Counter '\Processor(_Total)\% Processor Time' -ErrorAction Stop).CounterSamples[0].CookedValue),1) } catch {}
    Write-Row $out ("RESULT {0} load_s={1} decode_tps={2} prefill_tps={3} prompt_n={4} predicted_n={5} wall_s={6} board_mib={7} srv_ded_mib={8} srv_shr_mib={9} finish={10}" -f `
        $arm.tag, $s.load_s, $r.decode_tps, $r.prefill_tps, $r.prompt_n, $r.predicted_n, $r.wall_s, $v.board_mib, $v.srv_ded_mib, $v.srv_shr_mib, $r.finish)
    # server's own KV / offload lines
    $lines = @()
    foreach ($f in @($s.err, $s.out)) {
        if (Test-Path $f) { $lines += (Select-String -Path $f -Pattern 'KV self size|kv_unified|offloaded|n_layer|n_head_kv|n_embd_head|CUDA0 model buffer|CPU model buffer|graph nodes|n_ctx|MTP|mtp|load_tensors' | ForEach-Object { $_.Line.Trim() }) }
    }
    foreach ($l in ($lines | Select-Object -Unique)) { Write-Row $out ("  LOG {0}| {1}" -f $arm.tag, $l) }
    Stop-Srv
}
Write-Host 'PHASE2 DONE'

