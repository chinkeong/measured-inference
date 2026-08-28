# Same diagnostic probe, but launching llama-server directly with -ngld 99
# so the MTP draft context is also fully offloaded to GPU.
. (Join-Path $PSScriptRoot "..\gpu-lock.ps1")
$ErrorActionPreference = 'Stop'
$log = 'E:\AI\aider\qwen\server-log2.txt'
try { Get-Process llama-server -ErrorAction Stop | Stop-Process -Force -Confirm:$false } catch {}
Start-Sleep -Seconds 3
Remove-Item $log -ErrorAction SilentlyContinue

$exe = 'E:\AI\llama.cpp\llama-server.exe'
$model = 'C:\Users\chink\.lmstudio\models\lmstudio-community\Qwen3.8-27B-GGUF\Qwen3.8-27B-Q4_K_M.gguf'
$mmproj = 'C:\Users\chink\.lmstudio\models\lmstudio-community\Qwen3.8-27B-GGUF\mmproj-Qwen3.8-27B-BF16.gguf'
$args_ = @('-m', $model, '--mmproj', $mmproj, '--alias', 'qwen/qwen3.8-27b',
    '-c', '122880', '-ngl', '64', '-ngld', '99', '--parallel', '1', '--load-mode', 'none',
    '--api-key', 'dummy', '-ctk', 'q8_0', '-ctv', 'q8_0',
    '--spec-type', 'draft-mtp', '--spec-draft-n-max', '10', '--spec-draft-p-min', '0.5',
    '--temp', '1.0', '--top-p', '0.95', '--top-k', '20', '--min-p', '0.0',
    '--reasoning-preserve', '--image-min-tokens', '1024',
    '--chat-template-kwargs', '{\"reasoning_effort\":\"low\"}',
    '--jinja', '--host', '127.0.0.1', '--port', '1234')
$psi = Start-GuardedServer -FilePath $exe -ArgumentList $args_ -WindowStyle Hidden `
    -RedirectStandardError $log -RedirectStandardOutput 'E:\AI\aider\qwen\server-log2-out.txt' -PassThru

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

$body = @{ model='qwen/qwen3.8-27b'; temperature=0; top_k=1; max_tokens=700
           messages=@(@{role='user';content='Write a detailed 500-word technical explanation of how a marine aquarium nitrogen cycle works.'}) } | ConvertTo-Json -Depth 5
$sw = [Diagnostics.Stopwatch]::StartNew()
$resp = Invoke-RestMethod -Uri 'http://127.0.0.1:1234/v1/chat/completions' -Method Post `
    -ContentType 'application/json' -Headers @{Authorization='Bearer dummy'} `
    -Body ([Text.Encoding]::UTF8.GetBytes($body)) -TimeoutSec 0
$sw.Stop()
$tps = [math]::Round($resp.usage.completion_tokens / $sw.Elapsed.TotalSeconds, 1)
Write-Host "PROBE(-ngld 99): $($resp.usage.completion_tokens) tok in $([math]::Round($sw.Elapsed.TotalSeconds,1))s = $tps t/s"

Start-Sleep -Seconds 2
Write-Host '===== KEY SERVER LOG LINES ====='
Get-Content $log, 'E:\AI\aider\qwen\server-log2-out.txt' -ErrorAction SilentlyContinue |
    Select-String -Pattern 'offload|draft|spec|mtp|accept|eval time|threads' |
    ForEach-Object { $_.Line } | Select-Object -Last 30
