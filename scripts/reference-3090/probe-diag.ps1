# Diagnostic: start llama-server with console output captured, run one temp-0
# probe, then surface the server's own layer-offload / speculative-decoding /
# timing log lines.
$ErrorActionPreference = 'Stop'
$log = 'E:\AI\aider\qwen\server-log.txt'
try { Get-Process llama-server -ErrorAction Stop | Stop-Process -Force -Confirm:$false } catch {}
Start-Sleep -Seconds 3
Remove-Item $log -ErrorAction SilentlyContinue

# run the bat through cmd so both stdout+stderr of llama-server land in the log
Start-Process -FilePath 'cmd.exe' -ArgumentList '/c', 'E:\AI\aider\serve-qwen.bat low 122880 > E:\AI\aider\qwen\server-log.txt 2>&1' -WindowStyle Hidden

$ok = $false
for ($i = 0; $i -lt 600; $i++) {
    Start-Sleep -Seconds 2
    try {
        $h = Invoke-RestMethod 'http://127.0.0.1:1234/health' -TimeoutSec 2
        if ($h.status -eq 'ok') { $ok = $true; break }
    } catch {}
}
if (-not $ok) { Write-Host 'server never became healthy; log tail:'; Get-Content $log -Tail 40; exit 1 }

$body = @{ model='qwen/qwen3.8-27b'; temperature=0; top_k=1; max_tokens=700
           messages=@(@{role='user';content='Write a detailed 500-word technical explanation of how a marine aquarium nitrogen cycle works.'}) } | ConvertTo-Json -Depth 5
$sw = [Diagnostics.Stopwatch]::StartNew()
$resp = Invoke-RestMethod -Uri 'http://127.0.0.1:1234/v1/chat/completions' -Method Post `
    -ContentType 'application/json' -Headers @{Authorization='Bearer dummy'} `
    -Body ([Text.Encoding]::UTF8.GetBytes($body)) -TimeoutSec 0
$sw.Stop()
$tps = [math]::Round($resp.usage.completion_tokens / $sw.Elapsed.TotalSeconds, 1)
Write-Host "PROBE: $($resp.usage.completion_tokens) tok in $([math]::Round($sw.Elapsed.TotalSeconds,1))s = $tps t/s"
if ($resp.timings) { Write-Host ("SERVER TIMINGS: " + ($resp.timings | ConvertTo-Json -Compress)) }

Start-Sleep -Seconds 2
Write-Host '===== KEY SERVER LOG LINES ====='
Get-Content $log | Select-String -Pattern 'offload|ngl|layers to GPU|CUDA|draft|spec|mtp|KV self|n_ctx|accept|slot release|eval time|threads|warning|error' | ForEach-Object { $_.Line } | Select-Object -Last 60
