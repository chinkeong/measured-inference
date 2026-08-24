# window-ceiling-subq4.ps1 - what window do the sub-4-bit candidates actually
# need, at the shipped recipe, so a reader with ANY card can pick their -c.
#
# WHY NOT THE BALLAST THIS REPLACES. The plan of record called for a ballast
# process to hold VRAM so only 16,384 / 12,288 MiB stayed free, turning "fits
# in 16 GB" from derived into measured-under-an-emulated-budget. Two reasons
# that is the wrong instrument:
#   1. torch here is CPU-only, so there is no clean CUDA allocation to make a
#      precise ballast with; soaking VRAM with a second llama-server is
#      imprecise and puts two jobs on the card against rule 20.
#   2. More importantly it answers less than it appears to. A card's CAPACITY
#      requirement is a property of the model, the window and the flags - not
#      of the board - so it can be measured directly here and read off by an
#      owner of any card. What genuinely does NOT transfer is SPEED, which is
#      bandwidth-bound, and no amount of ballast on a 3090 fixes that.
# So: measure the REQUIREMENT properly across windows, publish it as a table a
# reader subtracts their own desktop from, and keep saying plainly that the
# speed column is this card's and nobody else's.
#
# Rule 13: two ceilings scoped to <file + drafter + projector + desktop>, the
# drafter measured as an on/off PAIR, and no window labelled without a
# deep-fill probe near its top. Rule 12: discard the first post-prefill probe.
# Rule 25 who-consumes: the -c line of every sub-Q4 recipe card, and the 16 GB
# and 12 GB rows of the card table in both documents, which today are derived.
param([int]$DeadlineMinutes = 150, [int]$MaxVramMiB = 2000)
$ErrorActionPreference = 'Continue'
. 'E:\AI\measured-inference\scripts\quant-ladder\ladder-lib.ps1'

$M      = 'C:\Users\chink\.lmstudio\models\unsloth\Qwen3.8-27B-GGUF'
$CORPUS = 'E:\AI\measured-inference\corpora\wikitext-2-raw-test.raw'
$DATA   = 'E:\AI\measured-inference\results\qwen38-27b-blind\data\quant-ladder'
$OUT    = Join-Path $DATA 'window-ceiling'
if (-not (Test-Path $OUT)) { New-Item -ItemType Directory -Path $OUT -Force | Out-Null }
$LED = Join-Path $OUT 'window-ceiling.txt'
if (-not (Test-Path $LED)) {
    Set-Content -LiteralPath $LED -Encoding utf8 -Value ('# 4-bit REFERENCE window ceilings, same windows as the sub-Q4 sweep, drafter on/off pairs - opened {0}' -f (Get-Date -Format 's'))
}
$PORT = 1235
$DEADLINE = (Get-Date).AddMinutes($DeadlineMinutes)
$raw = [IO.File]::ReadAllText($CORPUS)

$FILES = @(
    @{ tag = 'iq4xs'; path = "$M\Qwen3.8-27B-UD-IQ4_XS.gguf"; gib = 13.274 }
)
$WINDOWS = @(32768, 65536, 131072)
$SPECS = @(
    @{ tag = 'on';  flags = @('--spec-type','draft-mtp','--spec-draft-n-max','4','--spec-draft-p-min','0.75') },
    @{ tag = 'off'; flags = @('--spec-type','none') }
)

while ((Get-Date) -lt $DEADLINE) {
    $procs = @(Get-Process -Name 'llama-server','llama-perplexity','llama-cli','llama-bench' -ErrorAction SilentlyContinue).Count
    $v = 999999; try { $v = [int](& nvidia-smi --query-gpu=memory.used --format=csv,noheader,nounits | Select-Object -First 1) } catch {}
    if ($procs -eq 0 -and $v -lt $MaxVramMiB) { break }
    Write-Log ('waiting for the card - procs={0} vram={1}' -f $procs, $v); Start-Sleep -Seconds 45
}

foreach ($f in $FILES) {
  foreach ($w in $WINDOWS) {
    foreach ($s in $SPECS) {
      if ((Get-Date) -ge $DEADLINE) { Write-Log 'deadline'; break }
      $tag = '{0}-{1}-{2}' -f $f.tag, $w, $s.tag
      if (Test-LedgerHas $LED ('WIN ' + $tag + ' ')) { Write-Log ('skip ' + $tag); continue }

      $flags = @('-ngl','99','-c',"$w",'-fa','on','--parallel','1',
                 '-ctk','q8_0','-ctv','q8_0','--jinja','--reasoning','off') + $s.flags
      $srv = Start-Srv -ModelPath $f.path -Tag ('wc-' + $tag) -Flags $flags -Port $PORT -LogDir $OUT
      if (-not $srv) { Write-Ledger $LED ('WIN {0} | SRVFAIL at -c {1}' -f $tag, $w); continue }
      Start-Sleep -Seconds 4
      $load = 0; try { $load = [int](& nvidia-smi --query-gpu=memory.used --format=csv,noheader,nounits | Select-Object -First 1) } catch {}

      # deep fill to ~90% of the window (rule 13b), 4 chars/token coarse estimate
      $need = [int]($w * 0.90) * 4
      if ($raw.Length -lt $need) { $need = $raw.Length - 1 }
      $fill = $raw.Substring(0, $need) + "`n`nIn one sentence, name the most frequent topic above."
      $null = Invoke-Probe -Text $fill -MaxTokens 80 -Port $PORT -TimeoutSec 1800   # rule 12: discarded
      $deep = 0; try { $deep = [int](& nvidia-smi --query-gpu=memory.used --format=csv,noheader,nounits | Select-Object -First 1) } catch {}
      Start-Sleep -Seconds 8
      $rs = @()
      for ($i = 0; $i -lt 2; $i++) {
        $r = Invoke-Probe -Text $fill -MaxTokens 80 -Port $PORT -TimeoutSec 1800
        if ($r.ok) { $rs += $r }
        Start-Sleep -Seconds 3
      }
      Stop-Srv

      # the real prompt length lives in the server log, not in the cached probes
      $pn = 'n/a'; $len = 'n/a'
      $el = Join-Path $OUT ('srv-wc-{0}.err.log' -f $tag)
      if (Test-Path $el) {
        $t = Get-Content -Raw $el
        $m = [regex]::Matches($t, 'prompt eval time =\s*[\d.]+ ms /\s*(\d+) tokens')
        if ($m.Count) { $pn = $m[0].Groups[1].Value }
        $ml = [regex]::Matches($t, 'mean len =\s*([\d.]+)')
        if ($ml.Count) { $len = $ml[$ml.Count-1].Groups[1].Value }
      }
      if (-not $rs.Count) { Write-Ledger $LED ('WIN {0} | loaded {1} MiB but no settled probe' -f $tag, $load); continue }
      $tps = ($rs | Measure-Object -Property decode_tps -Average).Average
      Write-Ledger $LED ('WIN {0} | file={1} | GiB={2} | ctx={3} | drafter={4} | vram_at_load={5} MiB | vram_at_depth={6} MiB | fill_tokens={7} | decode_at_depth={8:N2} t/s | mean_draft_len={9} | probes={10} | load_s={11}' -f `
          $tag, $f.tag, $f.gib, $w, $s.tag, $load, $deep, $pn, $tps, $len, $rs.Count, $srv.load_s)
    }
  }
}
Write-Log 'WINDOW-CEILING DONE'
