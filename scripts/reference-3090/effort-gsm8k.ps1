# Does reasoning_effort change the GSM8K n=200 score?
# Three controlled runs on Q4_K_M: identical server/flags/prompts/decoding,
# only --chat-template-kwargs reasoning_effort differs.
. (Join-Path $PSScriptRoot "..\gpu-lock.ps1")
$ErrorActionPreference = 'Continue'
$dir = 'E:\AI\aider\qwen'
$model = 'C:\Users\chink\.lmstudio\models\lmstudio-community\Qwen3.8-27B-GGUF\Qwen3.8-27B-Q4_K_M.gguf'
$exe = 'E:\AI\llama.cpp\llama-server.exe'

foreach ($effort in @('low', 'medium', 'xhigh')) {
    try { Get-Process llama-server -ErrorAction Stop | Stop-Process -Force -Confirm:$false } catch {}
    Start-Sleep -Seconds 3
    Write-Output "===== EFFORT: $effort - starting server ====="
    $args_ = @('-m', $model, '--alias', 'qwen/qwen3.8-27b', '-c', '32768', '-ngl', '99',
        '--parallel', '1', '--load-mode', 'none',
        '-ctk', 'q8_0', '-ctv', 'q8_0',
        '--spec-type', 'draft-mtp', '--spec-draft-n-max', '4', '--spec-draft-p-min', '0.75',
        '--jinja', '--chat-template-kwargs', "{\`"reasoning_effort\`":\`"$effort\`"}",
        '--host', '127.0.0.1', '--port', '1234')
    Start-GuardedServer -FilePath $exe -ArgumentList $args_ -WindowStyle Hidden
    $ok = $false
    for ($i = 0; $i -lt 300; $i++) {
        Start-Sleep -Seconds 2
        try { $h = Invoke-RestMethod 'http://127.0.0.1:1234/health' -TimeoutSec 2; if ($h.status -eq 'ok') { $ok = $true; break } } catch {}
    }
    if (-not $ok) { Write-Output "[$effort] SERVER FAILED - skipping"; continue }

    Set-Location E:\AI\benchmark
    python bench.py --model $model --no-spawn --port 1234 --datasets GSM8K --samples 200 `
        --max-tokens 4096 --greedy --score 2>&1 | Select-Object -Last 15
    # tag the newest result json with the effort level
    $newest = Get-ChildItem E:\AI\benchmark\results\*.json | Sort-Object LastWriteTime -Descending | Select-Object -First 1
    if ($newest) { Copy-Item $newest.FullName (Join-Path $dir "gsm8k200-$effort.json") }
    Write-Output "===== EFFORT: $effort DONE ====="
}
try { Get-Process llama-server -ErrorAction Stop | Stop-Process -Force -Confirm:$false } catch {}
Write-Output 'EFFORT GSM8K DONE'
