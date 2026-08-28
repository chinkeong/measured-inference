# Negative-register entry 17(a): does the post-prefill clock state explain the
# deepest energy arm's 10.4% decode deficit?
#
# THE CLAIM UNDER TEST. Round 5's deepest arm reads 58.05 t/s where the cooled
# reference at the same depth and the same flags reads 64.76 - 10.4% low. The
# report explains that as a post-prefill clock state (rule 12, the clock-ramp
# trap): with prompt caching OFF, every probe in that arm fires immediately
# after a ~110-second prefill. The supporting evidence is that the cooled
# reference's OWN DISCARDED post-prefill probe reads 59.61, within 2.6% of the
# arm. That is a hypothesis with an obvious test and it was never run.
#
# THE TEST, and why it is better than the one the register proposed. The
# register says "re-run that arm with prompt caching on". Done naively that
# compares a new run against a number measured on a different day, so a drift
# in driver, clocks or ambient temperature confounds it. Instead this runs
# BOTH conditions inside ONE server load, at one depth, minutes apart:
#
#   probe 1  cache_prompt=true, first send  -> pays the full prefill, then
#            decodes IMMEDIATELY after it. This is the arm's condition.
#   probes 2+ same prompt, prefix now cached -> prefill is skipped entirely,
#            so decode does NOT follow a long compute burst. This is the
#            cooled condition.
#
# Same weights, same window, same flags, same depth, same session. The only
# thing that differs is whether a ~2-minute prefill happened immediately
# before the decode being timed.
#
# WHAT EACH OUTCOME MEANS, written down before the run (rule 2):
#   probes 2+ land near 64-65 t/s  -> hypothesis CONFIRMED. The deficit is the
#       clock state, the deepest row's decode half stays approximate, and
#       rule 12's discard-the-first-probe protocol is independently vindicated.
#   probes 2+ stay near 58 t/s     -> hypothesis REFUTED. The published
#       explanation is wrong and the 10.4% needs another cause. This is the
#       outcome that costs something, which is why it is written here first.
#   probes 2+ land between         -> partial. Report the number, claim nothing
#       about mechanism, and leave the register entry open with what was learned.
#
# Zero interpretation happens in this script. It prints what the server reports.

. (Join-Path $PSScriptRoot "..\gpu-lock.ps1")
$ErrorActionPreference = 'Continue'
$exe    = 'E:\AI\llama.cpp\llama-server.exe'
$model  = 'C:\Users\chink\.lmstudio\models\unsloth\Qwen3.8-27B-GGUF\Qwen3.8-27B-UD-IQ4_XS.gguf'
$outDir = 'E:\AI\measured-inference\results\qwen38-27b-blind\data\register'
$out    = Join-Path $outDir 'entry17a-clockramp.json'
New-Item -ItemType Directory -Force -Path $outDir | Out-Null

# Build a filler prompt targeting ~90,854 tokens - the depth of the arm under
# test. The line shape is copied from deep-decode-probe.ps1 so the token mix is
# the same kind of synthetic prose the original depth arms used.
$TARGET_LINES = 1548
$lines = New-Object System.Collections.Generic.List[string]
$lines.Add('Reference notes for the task below. Read them, then do the task at the end.')
for ($i = 1; $i -le $TARGET_LINES; $i++) {
    $frag = [Convert]::ToString((($i * 48271) % 1048573), 16)
    $lines.Add('Note ' + $i + ': subsystem alpha-' + (($i * 7) % 97) +
        ' reported latency ' + ((17 * $i) % 993) + ' ms on shard ' + ($i % 13) +
        ', retry budget ' + ((3 * $i) % 29) + ', digest fragment ' + $frag +
        ', remark: threshold crossed only when the moving median over window ' +
        ((5 * $i) % 47) + ' exceeded baseline by ' + ((11 * $i) % 83) + ' percent.')
}
$lines.Add('TASK: Write a single self-contained JavaScript file implementing a red-black tree class with insert, delete, search and an in-order iterator. Code only, no explanation.')
$longPrompt = [string]::Join("`n", $lines)

try { Get-Process llama-server -ErrorAction Stop | Stop-Process -Force -Confirm:$false } catch {}
Start-Sleep -Seconds 3

# The deepest depth arm's flags, verbatim: -c 131072, n4/p0.75, q8_0 KV.
$srvArgs = @('-m', $model, '--alias', 'qwen/qwen3.8-27b', '-c', '131072', '-ngl', '99',
    '--parallel', '1', '--load-mode', 'none', '-ctk', 'q8_0', '-ctv', 'q8_0',
    '--spec-type', 'draft-mtp', '--spec-draft-n-max', '4', '--spec-draft-p-min', '0.75',
    '--jinja', '--host', '127.0.0.1', '--port', '1234')
Write-Host 'starting server (UD-IQ4_XS, -c 131072, n4/p0.75, q8_0 KV)...'
Start-GuardedServer -FilePath $exe -ArgumentList $srvArgs -WindowStyle Hidden

$ok = $false
for ($i = 0; $i -lt 300; $i++) {
    Start-Sleep -Seconds 2
    try { $h = Invoke-RestMethod 'http://127.0.0.1:1234/health' -TimeoutSec 2
          if ($h.status -eq 'ok') { $ok = $true; break } } catch {}
}
if (-not $ok) { Write-Host 'SERVER FAILED TO COME UP'; exit 1 }
Write-Host 'server up.'

$probes = @()
for ($p = 1; $p -le 4; $p++) {
    $body = @{ model = 'qwen/qwen3.8-27b'; temperature = 0; top_k = 1
               max_tokens = 700; cache_prompt = $true
               messages = @(@{ role = 'user'; content = $longPrompt }) } |
            ConvertTo-Json -Depth 5 -Compress
    $sw = [Diagnostics.Stopwatch]::StartNew()
    $r = $null
    try {
        $r = Invoke-RestMethod -Uri 'http://127.0.0.1:1234/v1/chat/completions' `
            -Method Post -ContentType 'application/json' `
            -Body ([Text.Encoding]::UTF8.GetBytes($body)) -TimeoutSec 0
    } catch { Write-Host ("probe $p FAILED: $_") }
    $sw.Stop()
    if ($r -and $r.timings) {
        $t = $r.timings
        $rec = [pscustomobject]@{
            probe        = $p
            prompt_n     = $t.prompt_n
            prefill_s    = [math]::Round($t.prompt_ms / 1000, 1)
            prefill_tps  = [math]::Round($t.prompt_per_second, 1)
            decode_tps   = [math]::Round($t.predicted_per_second, 2)
            predicted_n  = $t.predicted_n
            draft_n      = $t.draft_n
            draft_acc    = $(if ($t.draft_n) { [math]::Round($t.draft_n_accepted / $t.draft_n, 3) } else { $null })
            wall_s       = [math]::Round($sw.Elapsed.TotalSeconds, 1)
            cached       = ($t.prompt_n -lt 100)
        }
        $probes += $rec
        Write-Host ("probe {0}: prompt_n {1,6}  prefill {2,6} s  DECODE {3,6} t/s  {4}" -f `
            $p, $t.prompt_n, $rec.prefill_s, $rec.decode_tps,
            $(if ($rec.cached) { '(prefix CACHED - no prefill before this decode)' }
              else { '(full prefill immediately before this decode)' }))
    }
}

$fresh  = @($probes | Where-Object { -not $_.cached })
$cached = @($probes | Where-Object { $_.cached })
$result = [pscustomobject]@{
    entry            = '17a'
    question         = 'Does the post-prefill clock state explain the deepest arm reading 58.05 t/s against a cooled 64.76?'
    published_arm    = 58.05
    published_cooled = 64.76
    published_discarded_postprefill = 59.61
    depth_target     = 90854
    flags            = 'UD-IQ4_XS, -c 131072, n4/p0.75, q8_0 KV, --parallel 1'
    date             = (Get-Date -Format 'yyyy-MM-dd HH:mm')
    probes           = $probes
    decode_after_prefill = $(if ($fresh.Count)  { [math]::Round((($fresh  | Measure-Object decode_tps -Average).Average), 2) } else { $null })
    decode_cached        = $(if ($cached.Count) { [math]::Round((($cached | Measure-Object decode_tps -Average).Average), 2) } else { $null })
}
$result | ConvertTo-Json -Depth 6 | Out-File -Encoding utf8 $out

Write-Host ''
Write-Host '================ ENTRY 17(a) RESULT ================'
Write-Host ("decode immediately after prefill : {0} t/s" -f $result.decode_after_prefill)
Write-Host ("decode with the prefix cached    : {0} t/s" -f $result.decode_cached)
Write-Host ("published arm 58.05 | published cooled 64.76 | published discarded post-prefill 59.61")
Write-Host ("-> $out")

try { Get-Process llama-server -ErrorAction Stop | Stop-Process -Force -Confirm:$false } catch {}
Write-Host 'server stopped. ENTRY 17a DONE'
