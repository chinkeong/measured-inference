# Follow-up M3 - q4_0 KV-cache perplexity check on UD-IQ4_XS.
#
# Third arm of the campaign's phase6 KV-quant series. Flags are byte-identical
# to phase6 (same binary, same model, same corpus, -ngl 99 -c 8192 -fa on
# --load-mode mmap) so the number drops straight into the existing table:
#     -ctk f16  -ctv f16  -> PPL 6.5956 +/- 0.04453   (baseline)
#     -ctk q8_0 -ctv q8_0 -> PPL 6.6160 +/- 0.04483   (+0.309 %)
#     -ctk q4_0 -ctv q4_0 -> THIS RUN
# The corpus at E:\AI\measured-inference\corpora\wikitext-2-raw-test.raw is
# SHA256-identical to the E:\AI\aider\qwen\wiki.test.raw phase6 used
# (173C87A5...DD08), so the three numbers are directly comparable.
$ErrorActionPreference = 'Continue'
$ppl    = 'E:\AI\llama.cpp\llama-perplexity.exe'
$model  = 'C:\Users\chink\.lmstudio\models\unsloth\Qwen3.8-27B-GGUF\Qwen3.8-27B-UD-IQ4_XS.gguf'
$corpus = 'E:\AI\measured-inference\corpora\wikitext-2-raw-test.raw'
$data   = 'E:\AI\measured-inference\results\qwen38-27b-blind\data\followup'
$log    = Join-Path $data 'm3-ppl-kv-q4_0.log'
$stamp  = Join-Path $data 'm3-ppl-kv-q4_0.txt'

foreach ($p in @($ppl, $model, $corpus)) {
    if (-not (Test-Path $p)) { Add-Content $stamp "M3 FATAL missing: $p" -Encoding utf8; exit 1 }
}
try { Get-Process llama-server -ErrorAction Stop | Stop-Process -Force -Confirm:$false } catch {}
Start-Sleep -Seconds 3

Add-Content $stamp ("M3 START {0}" -f (Get-Date -Format 'yyyy-MM-dd HH:mm:ss')) -Encoding utf8
Add-Content $stamp "M3 CMD llama-perplexity -m <UD-IQ4_XS> -f <wikitext-2-raw-test.raw> -ngl 99 -c 8192 -fa on --load-mode mmap -ctk q4_0 -ctv q4_0" -Encoding utf8

$sw = [Diagnostics.Stopwatch]::StartNew()
$txt = & $ppl -m $model -f $corpus -ngl 99 -c 8192 -fa on --load-mode mmap -ctk q4_0 -ctv q4_0 2>&1 | Out-String
$sw.Stop()
[IO.File]::WriteAllText($log, $txt, [Text.UTF8Encoding]::new($false))

$fin = (Select-String -Path $log -Pattern 'Final estimate' | Select-Object -Last 1)
Add-Content $stamp ("M3 WALL_S {0}" -f [math]::Round($sw.Elapsed.TotalSeconds, 1)) -Encoding utf8
Add-Content $stamp ("M3 RESULT {0}" -f $(if ($fin) { $fin.Line.Trim() } else { 'NO FINAL ESTIMATE - see log' })) -Encoding utf8
Add-Content $stamp ("M3 DONE {0}" -f (Get-Date -Format 'yyyy-MM-dd HH:mm:ss')) -Encoding utf8
