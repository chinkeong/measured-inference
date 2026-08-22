# Re-confirm every 3090 benchmark number the HTML guide cites, with -ngl 99
# (the old runs through serve-qwen*.bat may have carried the -ngl 64 handicap).
$ErrorActionPreference = 'Continue'
$code = 'Write a single self-contained JavaScript file implementing a red-black tree class with insert, delete, search and an in-order iterator. Code only, no explanation.'
$q4   = 'C:\Users\chink\.lmstudio\models\lmstudio-community\Qwen3.8-27B-GGUF\Qwen3.8-27B-Q4_K_M.gguf'
$nhi  = 'C:\Users\chink\.lmstudio\models\esatapedico\Qwen3.8-27B-NVFP4-MTP-GGUF\Qwen3.8-27B-NVFP4-MTP-HIGH.gguf'
$nvlo = 'C:\Users\chink\.lmstudio\models\esatapedico\Qwen3.8-27B-NVFP4-MTP-GGUF\Qwen3.8-27B-NVFP4-MTP-VERY-LOW.gguf'

function Run-Probe([string]$tag, [string]$model, [string]$ctx, [string[]]$flags) {
    Write-Output "===== $tag ====="
    $env:PROBE_MODEL = $model
    $env:PROBE_CTX   = $ctx
    $env:PROBE_TEXT  = $code
    powershell -NoProfile -ExecutionPolicy Bypass -File E:\AI\aider\qwen\probe-config.ps1 @flags 2>&1 |
        Where-Object { $_ -match 'PROBE|acceptance|exited|healthy' }
}

# Guide claim: 'Q4_K_M, no speculation: 40.3 t/s' at -c 32768
Run-Probe 'Q4_K_M baseline -c 32768 (guide: 40.3)' $q4 '32768' @('-ngl','99','--spec-type','none')
# Guide claim: 81.7 t/s with n-max 10 / p-min 0.5 (old optimal)
Run-Probe 'Q4_K_M MTP n10 p0.5 (guide: 81.7)' $q4 '122880' @('-ngl','99','--spec-type','draft-mtp','--spec-draft-n-max','10','--spec-draft-p-min','0.5')
# New tuned optimum for the guide to cite
Run-Probe 'Q4_K_M MTP n4 p0.75 (new optimum)' $q4 '122880' @('-ngl','99','--spec-type','draft-mtp','--spec-draft-n-max','4','--spec-draft-p-min','0.75')
# NVFP4 section: HIGH vs VERY-LOW, baseline + MTP, acceptance lengths (guide: 4.8 vs 3.33)
Run-Probe 'NVFP4-HIGH baseline' $nhi '122880' @('-ngl','99','--spec-type','none')
Run-Probe 'NVFP4-HIGH MTP n4 p0.75' $nhi '122880' @('-ngl','99','--spec-type','draft-mtp','--spec-draft-n-max','4','--spec-draft-p-min','0.75')
Run-Probe 'NVFP4-VERY-LOW MTP n4 p0.75' $nvlo '122880' @('-ngl','99','--spec-type','draft-mtp','--spec-draft-n-max','4','--spec-draft-p-min','0.75')

Remove-Item Env:PROBE_MODEL, Env:PROBE_CTX, Env:PROBE_TEXT -ErrorAction SilentlyContinue
Write-Output 'CONFIRM BENCHMARKS DONE'
