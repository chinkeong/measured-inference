# chain-0824b-rule7-alpaca.ps1 - the rule-7 remedy for the ONE truncation in
# the judge-gated pair.
#
# THE FINDING (judge-panel.py build, 2026-08-24): of the 150 kept ALPACA and
# MT-Bench answers, exactly one hit its cap - xhigh ALPACA[21], 16,384 tokens,
# content EMPTY. Same signature as the gemma runaway: the whole budget spent
# inside a thinking block that never closed.
#
# THE DECISION, made here and in advance (rule 25 - escalation is a decision,
# not a reflex): rerun it. Basis - the judge-gated pair is moving from
# "unscored by design" to SCORED, and rule 7 forbids publishing an arm's score
# with an unremedied truncation in it, and equally forbids the alternative of
# quietly dropping item 21. Cost ~20-30 min of GPU. It is a primary number:
# ALPACA and MT-Bench are the only open-ended-generation benchmarks in the
# suite, so they are where reasoning effort could plausibly show an effect that
# the five math/code benchmarks cannot see.
#
# COMPARABILITY: the cap binds only where it was hit. low ALPACA tops out at
# 2,033 tokens and medium at 1,714, so under greedy decoding their answers are
# byte-identical at any cap above that - raising the cap for xhigh alone
# changes nothing else. This is the same remedy the campaign already applied to
# MATH-500, HumanEval and MBPP.
#
# GPU-gated: waits for the ladder chain to finish AND the card to go quiet.
param(
    [int]$DeadlineMinutes = 720,
    [int]$MaxVramMiB = 2000
)
$ErrorActionPreference = 'Continue'
$DATA = 'E:\AI\measured-inference\results\qwen38-27b-blind\data\quant-ladder'
$WORK = 'E:\AI\measured-inference\results\qwen38-27b-blind\work'
$LOG  = Join-Path $DATA 'chain-0824b.log'
$SUITE = Join-Path $WORK 'rule21-n25-cap32768.json'
$DEADLINE = (Get-Date).AddMinutes($DeadlineMinutes)
function L([string]$m) { Add-Content -LiteralPath $LOG -Value ('[{0}] {1}' -f (Get-Date -Format 'MM-dd HH:mm:ss'), $m) }

L 'WAITER START - rule-7 rerun of xhigh ALPACA at cap 32768'
if (-not (Test-Path $SUITE)) { L ('FATAL - raised-cap suite missing: ' + $SUITE); exit 1 }

while ((Get-Date) -lt $DEADLINE) {
    $chainDone = (Test-Path (Join-Path $DATA 'chain-0824.log')) -and
                 (Select-String -Path (Join-Path $DATA 'chain-0824.log') -Pattern 'CHAIN DONE' -Quiet)
    $vram = 999999
    try { $vram = [int](& nvidia-smi --query-gpu=memory.used --format=csv,noheader,nounits | Select-Object -First 1) } catch {}
    $procs = @(Get-Process -Name 'llama-server','llama-perplexity','llama-cli','llama-bench','llama-tokenize' -ErrorAction SilentlyContinue).Count
    if ($chainDone -and $vram -lt $MaxVramMiB -and $procs -eq 0) {
        L ('gate OPEN - chain done, vram ' + $vram + ' MiB, no llama procs')
        break
    }
    L ('waiting - chainDone=' + $chainDone + ' vram=' + $vram + ' llamaProcs=' + $procs)
    Start-Sleep -Seconds 120
}
if ((Get-Date) -ge $DEADLINE) { L 'DEADLINE reached before the gate opened - NOT run'; exit 2 }

L 'launching rule21-arm.py xhigh ALPACA cap32768'
$py = 'C:\Python311\python.exe'
if (-not (Test-Path $py)) { $py = 'python' }
$p = Start-Process -FilePath $py -ArgumentList @('-u', (Join-Path $WORK 'rule21-arm.py'), 'xhigh', $SUITE, 'xhigh-alpaca-cap32k', 'ALPACA') `
    -NoNewWindow -PassThru `
    -RedirectStandardOutput (Join-Path $DATA 'rule7-alpaca.out.log') `
    -RedirectStandardError  (Join-Path $DATA 'rule7-alpaca.err.log')
$p.WaitForExit()
L ('rule21-arm exit=' + $p.ExitCode)
L 'RULE7-ALPACA DONE'
