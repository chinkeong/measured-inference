# Phase 6 (reduced) - perplexity on the wikitext-2-raw TEST split.
# Single quant campaign: this is an absolute number, not a ranking.
# Arm 1: fp16 KV cache. Arm 2: q8_0 KV cache -> verifies the KV-quant claim
# the recipes depend on. Resumable: an arm whose log already has a final
# estimate is skipped.
#
# Runs the remaining short GPU jobs first (the GPU is single-file either way,
# and perplexity plus the xhigh rerun are the long tail).
$ErrorActionPreference = 'Continue'
. 'E:\AI\measured-inference\results\qwen38-27b-blind\work\lib.ps1'
$ppl = 'E:\AI\llama.cpp\llama-perplexity.exe'
$corpus = 'E:\AI\aider\qwen\wiki.test.raw'
$WORK = 'E:\AI\measured-inference\results\qwen38-27b-blind\work'
$out = Join-Path $script:DATA 'phase6.txt'
if (-not (Test-Path $out)) { New-Item -ItemType File -Path $out | Out-Null }

foreach ($pre in @('phase8b.ps1','phase3d.ps1','phase4d.ps1','phase10b.ps1')) {
    Write-Host ("--- pre {0} {1} ---" -f $pre, (Get-Date -Format 'HH:mm:ss'))
    & powershell.exe -NoProfile -ExecutionPolicy Bypass -File (Join-Path $WORK $pre) 2>&1 |
        ForEach-Object { Write-Host $_ }
}
Stop-Srv

if (-not (Test-Path $corpus)) { Write-Row $out 'PHASE6 CORPUS MISSING' } else {
    $arms = @(
        @{ tag = 'ppl-kv-q8';  extra = @('-ctk','q8_0','-ctv','q8_0') },
        @{ tag = 'ppl-kv-f16'; extra = @('-ctk','f16','-ctv','f16') }
    )
    foreach ($a in $arms) {
        $log = Join-Path $script:DATA ($a.tag + '.log')
        if ((Test-Path $log) -and (Select-String -Path $log -Pattern 'Final estimate' -Quiet)) {
            Write-Host "skip $($a.tag) (done)"
        } else {
            Write-Host ("=== {0} {1} ===" -f $a.tag, (Get-Date -Format 'HH:mm:ss'))
            $sw = [Diagnostics.Stopwatch]::StartNew()
            $txt = & $ppl -m $script:MODEL -f $corpus -ngl 99 -c 8192 -fa on --load-mode mmap @($a.extra) 2>&1 | Out-String
            $sw.Stop()
            [IO.File]::WriteAllText($log, $txt, [Text.UTF8Encoding]::new($false))
            Write-Row $out ("TIMING {0} wall_s={1}" -f $a.tag, [math]::Round($sw.Elapsed.TotalSeconds, 1))
        }
        $fin = (Select-String -Path $log -Pattern 'Final estimate' | Select-Object -Last 1)
        $tok = (Select-String -Path $log -Pattern 'tokens in the file|n_ctx|Final estimate' | Select-Object -First 3 | ForEach-Object { $_.Line.Trim() }) -join ' ;; '
        Write-Row $out ("RESULT {0} | {1}" -f $a.tag, $(if ($fin) { $fin.Line.Trim() } else { 'NO FINAL ESTIMATE' }))
        Write-Row $out ("  META {0} | {1}" -f $a.tag, $tok)
    }
}

Write-Host ("--- xhigh rerun (last GPU job) {0} ---" -f (Get-Date -Format 'HH:mm:ss'))
& powershell.exe -NoProfile -ExecutionPolicy Bypass -File (Join-Path $WORK 'phase7b.ps1') 2>&1 |
    ForEach-Object { Write-Host $_ }
Write-Host 'PHASE6 DONE'
