# gemma-ppl-diag.ps1 - instrument-first isolation of the gemma perplexity anomaly.
#
# THE SYMPTOM: gemma-4-12B-it-QAT-Q4_0 measured PPL 1,159.72 (bpb 2.33) on the
# frozen wikitext-2 test corpus under the campaign's phase-6 conditions
# (-ngl 99 -c 8192 -fa on --load-mode mmap). A healthy 12B should read ~7-9.
#
# WHY IT IS THE INSTRUMENT AND NOT THE MODEL (two independent facts, rule 4):
#   1. The per-chunk trace is broken from the FIRST chunk: [1]2196.03, then
#      684-1160 for all 36. A model that had genuinely lost its language would
#      not start bad and stay flat - a context/cache defect degrades with depth.
#   2. The SAME file, same build, same -ngl 99 -c 8192 -fa on, generated 1,147
#      tokens of correct JavaScript at 82.1 t/s through llama-server and passed
#      every detector (JSON echo exact, fenced block clean, zero repetition).
#      A model at PPL 1,159 cannot write working code.
#
# So: isolate the apparatus before any number ships. Each arm runs 4 chunks
# (~40 s) - enough, because chunk [1] alone separates healthy from broken.
#
#   powershell -NoProfile -ExecutionPolicy Bypass -File gemma-ppl-diag.ps1
$ErrorActionPreference = 'Continue'
$here = Split-Path -Parent $MyInvocation.MyCommand.Path
. (Join-Path $here 'ladder-lib.ps1')

$PPL = 'E:\AI\llama.cpp\llama-perplexity.exe'
$CORPUS = 'E:\AI\measured-inference\corpora\wikitext-2-raw-test.raw'
$OUT = 'E:\AI\measured-inference\results\qwen38-27b-blind\data\quant-ladder\gemma-diag'
if (-not (Test-Path $OUT)) { New-Item -ItemType Directory -Path $OUT -Force | Out-Null }
$LEDGER = Join-Path $OUT 'diag.txt'
if (-not (Test-Path $LEDGER)) {
    Set-Content -LiteralPath $LEDGER -Value ('# gemma perplexity instrument isolation - opened {0}' -f (Get-Date -Format 's')) -Encoding utf8
}

$G12 = 'C:\Users\chink\.lmstudio\models\lmstudio-community\gemma-4-12B-it-QAT-GGUF\gemma-4-12B-it-QAT-Q4_0.gguf'
$GE2 = 'C:\Users\chink\.lmstudio\models\lmstudio-community\gemma-4-E2B-it-GGUF\gemma-4-E2B-it-Q8_0.gguf'
$QWEN = 'C:\Users\chink\.lmstudio\models\unsloth\Qwen3.8-27B-GGUF\Qwen3.8-27B-UD-IQ4_XS.gguf'

# tag | model | extra flags | chunks
# Baseline first: reproduce the failure, then change ONE thing at a time.
$arms = @(
    @{ t = 'A-repro-fa-on-c8192';   m = $G12;  f = @('-ngl','99','-c','8192','-fa','on','--load-mode','mmap'); c = 4 },
    @{ t = 'B-fa-OFF-c8192';        m = $G12;  f = @('-ngl','99','-c','8192','-fa','off','--load-mode','mmap'); c = 4 },
    @{ t = 'C-fa-on-SWAFULL';       m = $G12;  f = @('-ngl','99','-c','8192','-fa','on','--swa-full','--load-mode','mmap'); c = 4 },
    @{ t = 'D-fa-OFF-SWAFULL';      m = $G12;  f = @('-ngl','99','-c','8192','-fa','off','--swa-full','--load-mode','mmap'); c = 4 },
    @{ t = 'E-fa-on-c4096';         m = $G12;  f = @('-ngl','99','-c','4096','-fa','on','--load-mode','mmap'); c = 4 },
    @{ t = 'F-fa-on-c1024';         m = $G12;  f = @('-ngl','99','-c','1024','-fa','on','--load-mode','mmap'); c = 8 },
    @{ t = 'G-no-mmap-defaults';    m = $G12;  f = @('-ngl','99','-c','8192'); c = 4 },
    @{ t = 'H-E2B-Q8_0-same-flags'; m = $GE2;  f = @('-ngl','99','-c','8192','-fa','on','--load-mode','mmap'); c = 4 },
    @{ t = 'I-E2B-Q8_0-SWAFULL';    m = $GE2;  f = @('-ngl','99','-c','8192','-fa','on','--swa-full','--load-mode','mmap'); c = 4 },
    @{ t = 'J-CPU-ngl0-c2048';      m = $G12;  f = @('-ngl','0','-c','2048','-fa','off','--load-mode','mmap'); c = 2 },
    @{ t = 'K-qwen-control';        m = $QWEN; f = @('-ngl','99','-c','8192','-fa','on','--load-mode','mmap'); c = 4 },
    # Added after the literature search. -c 512 is llama-perplexity's OWN default
    # (main() sets n_ctx=512 before arg parsing), so it is what every published
    # number without an explicit -c actually used. Below the 1024 sliding window
    # neither SWA nor the global-layer path is stressed: if it is still ~1000
    # here, the fault is not in the attention path at all.
    @{ t = 'L-c512-default-ctx';    m = $G12;  f = @('-ngl','99','-c','512','-fa','on','--load-mode','mmap'); c = 16 },
    # Matched-protocol cross-measurer check: eaddario publishes gemma-4-E2B-it
    # F16 at 144.4897 on wikitext-2-raw-v1, -c 768. Our -c 8192 Q8_0 run read
    # 133.69. Re-running at HIS context turns "roughly similar" into a direct
    # comparison and tests whether this rig lands on an independently published
    # number for a model the whole ecosystem measures as broken.
    @{ t = 'M-E2B-c768-crosscheck'; m = $GE2;  f = @('-ngl','99','-c','768','-fa','on','--load-mode','mmap'); c = 16 }
)

# This script takes the GPU, so it obeys the same gate as everything else: the
# ladder runner may be live and one job at a time is the rule.
$MAN = Get-Manifest 'E:\AI\measured-inference\scripts\quant-ladder\ladder-manifest.json'
$DEADLINE = (Get-Date).AddMinutes(120)

foreach ($a in $arms) {
    $tag = $a.t
    if (Test-LedgerHas $LEDGER ('DIAG ' + $tag + ' ')) { Write-Log ("skip $tag (done)"); continue }
    if (-not (Test-Path -LiteralPath $a.m)) { Write-Log ("skip $tag - model missing"); continue }
    if (-not (Wait-GpuGate -Gate $MAN.gate -Deadline $DEADLINE)) { Write-Log 'gate never opened - stopping'; break }
    $log = Join-Path $OUT ('diag-{0}.err.log' -f $tag)
    $olog = Join-Path $OUT ('diag-{0}.out.log' -f $tag)
    $args1 = @('-m', $a.m, '-f', $CORPUS) + [string[]]$a.f + @('--chunks', "$($a.c)")
    Write-Log ("=== {0} :: {1}" -f $tag, (($a.f + @('--chunks', "$($a.c)")) -join ' '))
    $sw = [Diagnostics.Stopwatch]::StartNew()
    $p = Start-Process -FilePath $PPL -ArgumentList $args1 -NoNewWindow -PassThru `
        -RedirectStandardOutput $olog -RedirectStandardError $log
    if (-not $p.WaitForExit(1800000)) { try { $p.Kill() } catch {} }
    $sw.Stop()
    $txt = ''
    foreach ($f in @($log, $olog)) { if (Test-Path $f) { $txt += (Get-Content -Raw -LiteralPath $f -ErrorAction SilentlyContinue) } }
    $fin = [regex]::Match($txt, 'Final estimate:\s*PPL\s*=\s*([0-9.,]+)\s*\+/-\s*([0-9.,]+)')
    $c1 = [regex]::Match($txt, '\[1\]([0-9.,]+)')
    $ctx = [regex]::Match($txt, 'n_ctx=(\d+)')
    $why = ''
    if (-not $fin.Success) {
        $why = 'NO-FINAL-ESTIMATE'
        $e = [regex]::Match($txt, '(?im)^.*(error|failed|not supported|unsupported).*$')
        if ($e.Success) { $why = $e.Value.Trim() }
        if ($why.Length -gt 150) { $why = $why.Substring(0, 150) }
    }
    Write-Ledger $LEDGER ('DIAG {0} | model={1} | flags={2} | chunks={3} | chunk1={4} | PPL={5} | err={6} | n_ctx={7} | wall_s={8} | {9}' -f `
        $tag, (Split-Path -Leaf $a.m), (($a.f) -join ' '), $a.c,
        $(if ($c1.Success) { $c1.Groups[1].Value } else { '-' }),
        $(if ($fin.Success) { $fin.Groups[1].Value } else { '-' }),
        $(if ($fin.Success) { $fin.Groups[2].Value } else { '-' }),
        $(if ($ctx.Success) { $ctx.Groups[1].Value } else { '-' }),
        [math]::Round($sw.Elapsed.TotalSeconds, 1), $why)
}
Write-Log 'GEMMA-DIAG DONE'
