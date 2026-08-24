# decisive-arm.ps1 - the equal-budget arm of the quant-ladder campaign.
#
#   powershell -NoProfile -ExecutionPolicy Bypass -File decisive-arm.ps1 `
#       -Arms "gemma-12b-q4_0|C:\...\gemma-4-12B-it-QAT-Q4_0.gguf|gemma","qwen-iq2xxs|C:\...\UD-IQ2_XXS.gguf|qwen"
#
# THE QUESTION: at ~6.5 GiB of weights, is a 12B trained for 4 bits better than
# a 27B crushed to the same file size? Perplexity cannot answer it (rule 6:
# different tokenizers), so this is decided on scored benchmarks, which are
# tokenizer-independent.
#
# GPU-gated (one job at a time), resumable (an arm whose wall.json exists is
# skipped), and rule-7 compliant: an arm that truncates is RERUN at 32,768 -
# only that arm, never a filter to non-truncating questions.
param(
    [string[]]$Arms,
    [string]$Manifest = 'E:\AI\measured-inference\scripts\quant-ladder\ladder-manifest.json',
    [int]$DeadlineMinutes = 300,
    [switch]$SkipGate,
    # Rule 25: the rule-7 cap raise fires ONLY for arms named here. Truncations
    # are always reported; the RERUN is a priced decision made before launch.
    [string[]]$EscalateArms = @()
)

$ErrorActionPreference = 'Continue'
$here = Split-Path -Parent $MyInvocation.MyCommand.Path
. (Join-Path $here 'ladder-lib.ps1')

$M = Get-Manifest $Manifest
$OUT = Join-Path ([string]$M.outdir) 'bench'
if (-not (Test-Path $OUT)) { New-Item -ItemType Directory -Path $OUT -Force | Out-Null }
$LOG = Join-Path ([string]$M.outdir) 'decisive.txt'
if (-not (Test-Path $LOG)) {
    Set-Content -LiteralPath $LOG -Value ('# decisive (equal-budget) arm ledger - opened {0}' -f (Get-Date -Format 's')) -Encoding utf8
}
$DEADLINE = (Get-Date).AddMinutes($DeadlineMinutes)
$PY = 'C:\Python311\python.exe'
if (-not (Test-Path $PY)) { $PY = 'python' }

function Get-ArmJson {
    param([string]$Tag)
    $f = Get-ChildItem $OUT -Filter ('arm-{0}-*.json' -f $Tag) -ErrorAction SilentlyContinue |
        Where-Object { $_.Name -notmatch 'transcripts|wall' } | Sort-Object LastWriteTime | Select-Object -Last 1
    if (-not $f) { return $null }
    try { return (Get-Content -Raw $f.FullName | ConvertFrom-Json) } catch { return $null }
}

function Invoke-Arm {
    param([string]$Tag, [string]$Path, [string]$Family, [string]$MaxTokens = '16384')
    if (Test-Path (Join-Path $OUT ('arm-{0}-wall.json' -f $Tag))) {
        Write-Log ('arm {0}: already done - skipping' -f $Tag)
        return
    }
    if (-not (Test-Path -LiteralPath $Path)) { Write-Log ('arm {0}: model missing {1}' -f $Tag, $Path); return }
    if (-not $SkipGate) {
        if (-not (Wait-GpuGate -Gate $M.gate -Deadline $DEADLINE)) { return }
    }
    Write-Log ('=== ARM {0} ({1}, cap {2}) ===' -f $Tag, $Family, $MaxTokens)
    $armLog = Join-Path $OUT ('arm-{0}.console.log' -f $Tag)
    $armErr = Join-Path $OUT ('arm-{0}.console.err' -f $Tag)
    $a = @('-u', (Join-Path $here 'bench-arm.py'), $Tag, $Path, $Family, $MaxTokens)
    $sw = [Diagnostics.Stopwatch]::StartNew()
    $p = Start-Process -FilePath $PY -ArgumentList $a -NoNewWindow -PassThru `
        -RedirectStandardOutput $armLog -RedirectStandardError $armErr
    if (-not $p.WaitForExit(21600000)) { Write-Log ('arm {0}: TIMEOUT 6 h - killing' -f $Tag); try { $p.Kill() } catch {} }
    $sw.Stop()
    Stop-Srv
    $j = Get-ArmJson -Tag $Tag
    if (-not $j) {
        Write-Ledger $LOG ('ARM {0} | FAILED - no result json (see arm-{0}.console.err) | wall_s={1}' -f $Tag, [math]::Round($sw.Elapsed.TotalSeconds, 1))
        return
    }
    $parts = @()
    $trunc = 0
    foreach ($ds in $j.datasets) {
        $r = $j.results.$ds
        $t = 0
        if ($r.PSObject.Properties.Name -contains 'truncated_n') { $t = [int]$r.truncated_n }
        $trunc += $t
        $parts += ('{0}={1:N1}(n={2},trunc={3})' -f $ds, $r.score, $r.graded_n, $t)
    }
    Write-Ledger $LOG ('ARM {0} | model={1} | cap={2} | mean={3:N2} | {4} | truncations={5} | wall_s={6} | suite={7} | ts={8}' -f `
        $Tag, $j.model_label, $MaxTokens, $j.composite.mean, ($parts -join ' '), $trunc,
        [math]::Round($sw.Elapsed.TotalSeconds, 1), $j.suite_hash, (Get-Date -Format 's'))

    if ($trunc -gt 0 -and $MaxTokens -eq '16384') {
        # RULE 25: an escalation is a DECISION, not a reflex. This used to fire
        # automatically, and on 2026-08-24 it fired on UD-IQ1_S - a file that
        # had already FAILED its detector screen - consuming 1.6 h of a
        # projected 4-5 h and starving the probe that answered the reader's
        # actual question, which died on its own deadline having run nothing.
        # The raise is now opt-in per arm.
        if ($EscalateArms -contains $Tag) {
            Write-Ledger $LOG ('RULE7 {0} | {1} truncation(s) at cap 16384 - raise PRE-AUTHORISED for this arm, rerunning THIS ARM ONLY at 32768 (greedy determinism leaves the others byte-identical)' -f $Tag, $trunc)
            Invoke-Arm -Tag ($Tag + '-cap32k') -Path $Path -Family $Family -MaxTokens '32768'
        } else {
            Write-Ledger $LOG ('RULE7 {0} | {1} truncation(s) at cap 16384 - raise NOT authorised for this arm, so NOT run (rule 25: escalation is a decision). Pass -EscalateArms {0} to authorise it. Truncations are reported with the score; if this arm is a screened-out file or a secondary, the raise usually buys nothing - rule 7 makes the raise a DIAGNOSTIC, and a reproduced truncation is already established for this model family.' -f $Tag, $trunc)
        }
    }
}

foreach ($spec in $Arms) {
    if ((Get-Date) -ge $DEADLINE) { Write-Log 'deadline reached'; break }
    $f = $spec -split '\|'
    if ($f.Count -lt 3) { Write-Log ('bad arm spec: {0}' -f $spec); continue }
    Invoke-Arm -Tag $f[0] -Path $f[1] -Family $f[2]
}
Write-Log 'DECISIVE DONE'
