# Parameterized probe: pass extra llama-server args after the script name.
# Example: probe-config.ps1 --spec-type none
#
# WARNING - the default below is '-ngl 64' and that is the off-by-one trap
# METHODOLOGY rule 15 exists to prevent (llama.cpp counts the output projection
# as layer n+1; leaving it on the CPU cost this campaign ~35% of decode speed).
# It is safe here ONLY because every caller appends '-ngl 99' in its extra args,
# which wins as the later occurrence. Callers in this directory all do:
# spec-sweep.ps1, spec-sweep2.ps1, confirm-benchmarks.ps1.
# If you invoke this script standalone or adapt it, PASS '-ngl 99' YOURSELF.
# (Left as-is rather than fixed: this is the file as it ran, and the numbers in
# the example report were produced by it.)
$ErrorActionPreference = 'Stop'
$extra = $args
$log = 'E:\AI\aider\qwen\server-probe-err.txt'
$logOut = 'E:\AI\aider\qwen\server-probe-out.txt'
try { Get-Process llama-server -ErrorAction Stop | Stop-Process -Force -Confirm:$false } catch {}
Start-Sleep -Seconds 3
Remove-Item $log, $logOut -ErrorAction SilentlyContinue

$exe = 'E:\AI\llama.cpp\llama-server.exe'
$model = 'C:\Users\chink\.lmstudio\models\lmstudio-community\Qwen3.8-27B-GGUF\Qwen3.8-27B-Q4_K_M.gguf'
if ($env:PROBE_MODEL) { $model = $env:PROBE_MODEL }
$ctx = '122880'
if ($env:PROBE_CTX) { $ctx = $env:PROBE_CTX }
$mmproj = 'C:\Users\chink\.lmstudio\models\lmstudio-community\Qwen3.8-27B-GGUF\mmproj-Qwen3.8-27B-BF16.gguf'
$args_ = @('-m', $model, '--mmproj', $mmproj, '--alias', 'qwen/qwen3.8-27b',
    '-c', $ctx, '-ngl', '64', '--parallel', '1', '--load-mode', 'none',
    '--api-key', 'dummy', '-ctk', 'q8_0', '-ctv', 'q8_0',
    '--temp', '1.0', '--top-p', '0.95', '--top-k', '20', '--min-p', '0.0',
    '--reasoning-preserve', '--image-min-tokens', '1024',
    '--chat-template-kwargs', '{\"reasoning_effort\":\"low\"}',
    '--jinja', '--host', '127.0.0.1', '--port', '1234') + $extra
$psi = Start-Process -FilePath $exe -ArgumentList $args_ -WindowStyle Hidden `
    -RedirectStandardError $log -RedirectStandardOutput $logOut -PassThru

$ok = $false
for ($i = 0; $i -lt 600; $i++) {
    Start-Sleep -Seconds 2
    try {
        $h = Invoke-RestMethod 'http://127.0.0.1:1234/health' -TimeoutSec 2
        if ($h.status -eq 'ok') { $ok = $true; break }
    } catch {}
    if ($psi.HasExited) { Write-Host "server exited code $($psi.ExitCode); log tail:"; Get-Content $log -Tail 30; exit 1 }
}
if (-not $ok) { Write-Host 'server never became healthy; log tail:'; Get-Content $log -Tail 30; exit 1 }

$probeText = 'Write a detailed 500-word technical explanation of how a marine aquarium nitrogen cycle works.'
if ($env:PROBE_TEXT) { $probeText = $env:PROBE_TEXT }
$body = @{ model='qwen/qwen3.8-27b'; temperature=0; top_k=1; max_tokens=700
           messages=@(@{role='user';content=$probeText}) } | ConvertTo-Json -Depth 5
$sw = [Diagnostics.Stopwatch]::StartNew()
$resp = Invoke-RestMethod -Uri 'http://127.0.0.1:1234/v1/chat/completions' -Method Post `
    -ContentType 'application/json' -Headers @{Authorization='Bearer dummy'} `
    -Body ([Text.Encoding]::UTF8.GetBytes($body)) -TimeoutSec 0
$sw.Stop()
$tps = [math]::Round($resp.usage.completion_tokens / $sw.Elapsed.TotalSeconds, 1)
Write-Host "PROBE [$($extra -join ' ')]: $($resp.usage.completion_tokens) tok in $([math]::Round($sw.Elapsed.TotalSeconds,1))s = $tps t/s"

Start-Sleep -Seconds 2
Get-Content $log, $logOut -ErrorAction SilentlyContinue |
    Select-String -Pattern 'accept|eval time|draft' | ForEach-Object { $_.Line } | Select-Object -Last 6
try { Get-Process llama-server -ErrorAction Stop | Stop-Process -Force -Confirm:$false } catch {}
