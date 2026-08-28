# Corrected deep probe: report the SERVER's own timing split (prefill vs decode)
# at ~27k-token depth for the promoted config [1] (IQ4_XS text-only -c 196608).
. (Join-Path $PSScriptRoot "..\gpu-lock.ps1")
$ErrorActionPreference = 'Continue'
$exe = 'E:\AI\llama.cpp\llama-server.exe'
$model = 'C:\Users\chink\.lmstudio\models\unsloth\Qwen3.8-27B-GGUF\Qwen3.8-27B-UD-IQ4_XS.gguf'
$code = 'Write a single self-contained JavaScript file implementing a red-black tree class with insert, delete, search and an in-order iterator. Code only, no explanation.'
$lines = New-Object System.Collections.Generic.List[string]
$lines.Add('Reference notes for the task below. Read them, then do the task at the end.')
for ($i = 1; $i -le 460; $i++) {
    $frag = [Convert]::ToString((($i * 48271) % 1048573), 16)
    $l = 'Note ' + $i + ': subsystem alpha-' + (($i * 7) % 97) + ' reported latency ' + ((17 * $i) % 993) + ' ms on shard ' + ($i % 13) + ', retry budget ' + ((3 * $i) % 29) + ', digest fragment ' + $frag + ', remark: threshold crossed only when the moving median over window ' + ((5 * $i) % 47) + ' exceeded baseline by ' + ((11 * $i) % 83) + ' percent.'
    $lines.Add($l)
}
$lines.Add('TASK: ' + $code)
$longPrompt = [string]::Join("`n", $lines)

try { Get-Process llama-server -ErrorAction Stop | Stop-Process -Force -Confirm:$false } catch {}
Start-Sleep -Seconds 3
$args_ = @('-m', $model, '--alias', 'qwen/qwen3.8-27b', '-c', '196608', '-ngl', '99',
    '--parallel', '1', '--load-mode', 'none', '-ctk', 'q8_0', '-ctv', 'q8_0',
    '--spec-type', 'draft-mtp', '--spec-draft-n-max', '4', '--spec-draft-p-min', '0.75',
    '--jinja', '--host', '127.0.0.1', '--port', '1234')
Start-GuardedServer -FilePath $exe -ArgumentList $args_ -WindowStyle Hidden
$ok = $false
for ($i = 0; $i -lt 300; $i++) { Start-Sleep -Seconds 2
    try { $h = Invoke-RestMethod 'http://127.0.0.1:1234/health' -TimeoutSec 2; if ($h.status -eq 'ok') { $ok = $true; break } } catch {} }
if (-not $ok) { Write-Output 'SERVER FAILED'; exit 1 }

$body = @{ model='qwen/qwen3.8-27b'; temperature=0; top_k=1; max_tokens=700
           messages=@(@{role='user';content=$longPrompt}) } | ConvertTo-Json -Depth 5
$r = Invoke-RestMethod -Uri 'http://127.0.0.1:1234/v1/chat/completions' -Method Post `
    -ContentType 'application/json' -Body ([Text.Encoding]::UTF8.GetBytes($body)) -TimeoutSec 0
if ($r.timings) {
    Write-Output ('prompt tokens : ' + $r.timings.prompt_n + '  prefill ' + [math]::Round($r.timings.prompt_per_second, 1) + ' t/s (' + [math]::Round($r.timings.prompt_ms/1000, 1) + ' s)')
    Write-Output ('DECODE at depth: ' + [math]::Round($r.timings.predicted_per_second, 1) + ' t/s over ' + $r.timings.predicted_n + ' tokens')
    if ($r.timings.draft_n) { Write-Output ('draft acceptance: ' + [math]::Round($r.timings.draft_n_accepted / $r.timings.draft_n, 2)) }
} else { Write-Output 'no timings in response' }
try { Get-Process llama-server -ErrorAction Stop | Stop-Process -Force -Confirm:$false } catch {}
Write-Output 'DEEP DECODE PROBE DONE'
