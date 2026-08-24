# chain-0824.ps1 - serialize the three remaining GPU jobs of the quant-ladder
# campaign after the 05:47 deadline exit. One GPU, one job at a time (rule 20):
#   1. gemma-trunc-probe.ps1   (short: 2 arms x 2 prompts, <=4096 tok each)
#   2. decisive-arm.ps1        qwen-iq2xxs - the PRIMARY equal-budget arm
#   3. run-ladder.ps1          pass-2 infill UD-IQ2_S (file lands via the
#                              parallel download this session started)
# Each child writes its own out/err logs in $DATA; this script stamps a chain
# log between steps. Liveness: watchdog reads the chain log + the active
# child's out.log + nvidia-smi.
$ErrorActionPreference = 'Continue'
$SC   = 'E:\AI\measured-inference\scripts\quant-ladder'
$DATA = 'E:\AI\measured-inference\results\qwen38-27b-blind\data\quant-ladder'
$LOG  = Join-Path $DATA 'chain-0824.log'
function L([string]$m) { Add-Content -LiteralPath $LOG -Value ('[{0}] {1}' -f (Get-Date -Format 'MM-dd HH:mm:ss'), $m) }

function RunStep([string]$name, [string]$file, [string[]]$extra) {
    L ('step start: ' + $name)
    $args = @('-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', $file) + $extra
    $p = Start-Process -FilePath 'powershell.exe' -ArgumentList $args -NoNewWindow -PassThru `
        -RedirectStandardOutput (Join-Path $DATA ($name + '.out.log')) `
        -RedirectStandardError  (Join-Path $DATA ($name + '.err.log'))
    $p.WaitForExit()
    L ('step done: ' + $name + ' exit=' + $p.ExitCode)
}

L 'CHAIN START: trunc-probe -> qwen decisive arm -> ladder pass-2'

# Rule 25 (escalation is a decision): the rule-7 cap raise 16384->32768 on
# truncation is PRE-AUTHORIZED for the qwen-iq2xxs arm, decided by the session
# 2026-08-24 11:20 BEFORE launch. Basis: this is the PRIMARY decisive arm of
# the ladder question (not a secondary-arm auto-escalation like the gemma
# cap-32k case study), and its comparator already carries a cap-32k arm.
Add-Content -LiteralPath (Join-Path $DATA 'decisive.txt') -Value 'DECISION qwen-iq2xxs | rule-7 cap raise on truncation PRE-AUTHORIZED by the session 2026-08-24T11:20 before launch - primary decisive arm, comparator already has a cap-32k arm (rule 25: escalation is a decision, made here, in advance)'

RunStep 'chain-trunc-probe' (Join-Path $SC 'gemma-trunc-probe.ps1') @('-DeadlineMinutes', '120')
RunStep 'chain-decisive-qwen' (Join-Path $SC 'decisive-arm.ps1') @('-Arms', 'qwen-iq2xxs|C:\Users\chink\.lmstudio\models\unsloth\Qwen3.8-27B-GGUF\Qwen3.8-27B-UD-IQ2_XXS.gguf|qwen', '-DeadlineMinutes', '600')
RunStep 'chain-ladder-pass2' (Join-Path $SC 'run-ladder.ps1') @('-DeadlineMinutes', '480')

L 'CHAIN DONE'
