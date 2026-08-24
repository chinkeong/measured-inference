# depth131k-replicate.ps1 - replicate the 98,304 drafter-ON arms before any
# ordering between them is published.
#
# THE PROBLEM. The window-ceiling sweep measured, at -c 98,304 with the
# drafter on and n=2 settled probes each:
#     UD-Q3_K_XL  41.68 t/s   mean draft length 3.30
#     UD-IQ4_XS   34.35 t/s   mean draft length 3.43
#     UD-Q2_K_XL  28.76 t/s   mean draft length 3.20
# Read naively that says the 3.9-bpw file is 21% faster than the 4-bit file at
# depth. TWO REASONS NOT TO BELIEVE IT YET:
#   1. Bandwidth alone predicts only ~8% (13.274 / 12.244), not 21%.
#   2. It is internally inconsistent. UD-IQ4_XS has the LONGER mean draft
#      length of the two (3.43 against 3.30) and is nonetheless the slower -
#      the opposite of rule 11's mechanism, which has held everywhere else in
#      this campaign. When the proposed effect contradicts the mechanism that
#      produced every other result, suspect the measurement.
# n=2 probes cannot separate 21% from clock state or a warm-up artefact. Rule
# 26: a level read off one or two probes carries a band, and the campaign's own
# floor is ~3% on slow arms and up to +/-25% on single probes.
#
# THIS ARM: the same three configurations, n=5 settled probes each, the first
# post-prefill probe discarded (rule 12), and a 30 s settle after the fill so
# clocks are steady (rule 12's ramp trap: a probe fired straight after a long
# prefill reads up to 45% low). If the ordering survives at n=5 it is real and
# publishable; if it collapses, the sweep's 131k row gets a band, not a rank.
# Rule 25 who-consumes: the depth column of the recipe cards, and any sentence
# that would tell a 24 GB reader which file is fastest at long context.
param([int]$DeadlineMinutes = 60, [int]$MaxVramMiB = 2000)
$ErrorActionPreference = 'Continue'
. 'E:\AI\measured-inference\scripts\quant-ladder\ladder-lib.ps1'

$M      = 'C:\Users\chink\.lmstudio\models\unsloth\Qwen3.8-27B-GGUF'
$CORPUS = 'E:\AI\measured-inference\corpora\wikitext-2-raw-test.raw'
$DATA   = 'E:\AI\measured-inference\results\qwen38-27b-blind\data\quant-ladder'
$OUT    = Join-Path $DATA 'q3kxl-instability'
if (-not (Test-Path $OUT)) { New-Item -ItemType Directory -Path $OUT -Force | Out-Null }
$LED = Join-Path $OUT 'q3kxl-instability.txt'
if (-not (Test-Path $LED)) {
    Set-Content -LiteralPath $LED -Encoding utf8 -Value ('# 98k crossover point, n=5 settled probes - opened {0}' -f (Get-Date -Format 's'))
}
$PORT = 1235
$DEADLINE = (Get-Date).AddMinutes($DeadlineMinutes)
$raw = [IO.File]::ReadAllText($CORPUS)
$need = [int](98304 * 0.90) * 4
if ($raw.Length -lt $need) { $need = $raw.Length - 1 }
$FILL = $raw.Substring(0, $need) + "`n`nIn one sentence, name the most frequent topic above."

$ARMS = @(
    @{ tag = 'q3kxl-r2'; path = "$M\Qwen3.8-27B-UD-Q3_K_XL.gguf"; gib = 12.244 }
)

while ((Get-Date) -lt $DEADLINE) {
    $procs = @(Get-Process -Name 'llama-server','llama-perplexity','llama-cli','llama-bench' -ErrorAction SilentlyContinue).Count
    $v = 999999; try { $v = [int](& nvidia-smi --query-gpu=memory.used --format=csv,noheader,nounits | Select-Object -First 1) } catch {}
    if ($procs -eq 0 -and $v -lt $MaxVramMiB) { break }
    Write-Log ('waiting for the card - procs={0} vram={1}' -f $procs, $v); Start-Sleep -Seconds 45
}

foreach ($a in $ARMS) {
    if ((Get-Date) -ge $DEADLINE) { break }
    if (Test-LedgerHas $LED ('REP ' + $a.tag + ' ')) { Write-Log ('skip ' + $a.tag); continue }
    $flags = @('-ngl','99','-c','98304','-fa','on','--parallel','1',
               '-ctk','q8_0','-ctv','q8_0','--jinja','--reasoning','off',
               '--spec-type','draft-mtp','--spec-draft-n-max','4','--spec-draft-p-min','0.75')
    $srv = Start-Srv -ModelPath $a.path -Tag ('q3i-' + $a.tag) -Flags $flags -Port $PORT -LogDir $OUT
    if (-not $srv) { Write-Ledger $LED ('REP {0} | SRVFAIL' -f $a.tag); continue }

    $null = Invoke-Probe -Text $FILL -MaxTokens 80 -Port $PORT -TimeoutSec 1800   # rule 12: discarded
    Start-Sleep -Seconds 30                                                        # let clocks settle
    $tp = @()
    for ($i = 0; $i -lt 5; $i++) {
        $r = Invoke-Probe -Text $FILL -MaxTokens 80 -Port $PORT -TimeoutSec 1800
        if ($r.ok) { $tp += [double]$r.decode_tps }
        Start-Sleep -Seconds 4
    }
    Stop-Srv
    if ($tp.Count -lt 2) { Write-Ledger $LED ('REP {0} | only {1} probe(s)' -f $a.tag, $tp.Count); continue }
    $mean = ($tp | Measure-Object -Average).Average
    $mn   = ($tp | Measure-Object -Minimum).Minimum
    $mx   = ($tp | Measure-Object -Maximum).Maximum
    $sd   = [math]::Sqrt((($tp | ForEach-Object { ($_ - $mean) * ($_ - $mean) }) | Measure-Object -Sum).Sum / $tp.Count)
    $len = 'n/a'; $acc = 'n/a'
    $el = Join-Path $OUT ('srv-q3i-{0}.err.log' -f $a.tag)
    if (Test-Path $el) {
        $t = Get-Content -Raw $el
        $ml = [regex]::Matches($t, 'mean len =\s*([\d.]+)')
        if ($ml.Count) { $len = $ml[$ml.Count-1].Groups[1].Value }
        $ma = [regex]::Matches($t, 'draft acceptance = ([\d.]+)')
        if ($ma.Count) { $acc = $ma[$ma.Count-1].Groups[1].Value }
    }
    Write-Ledger $LED ('REP {0} | GiB={1} | ctx=98304 | drafter=on n4/p0.75 | n={2} | mean={3:N2} t/s | min={4:N2} | max={5:N2} | sd={6:N2} | spread_pct={7:N1} | acceptance={8} | mean_draft_len={9} | probes=[{10}]' -f `
        $a.tag, $a.gib, $tp.Count, $mean, $mn, $mx, $sd, (($mx - $mn) / $mean * 100), $acc, $len, (($tp | ForEach-Object { '{0:N2}' -f $_ }) -join ' '))
}
Write-Log 'Q3KXL-INSTABILITY DONE'
