# xhigh GSM8K n=200 rerun with max_tokens 16384 (removes the 4096 budget artifact).
# low/medium need no rerun: greedy + zero truncations = byte-identical under any cap.
$ErrorActionPreference = 'Continue'
$exe = 'E:\AI\llama.cpp\llama-server.exe'
$model = 'C:\Users\chink\.lmstudio\models\lmstudio-community\Qwen3.8-27B-GGUF\Qwen3.8-27B-Q4_K_M.gguf'
try { Get-Process llama-server -ErrorAction Stop | Stop-Process -Force -Confirm:$false } catch {}
Start-Sleep -Seconds 3
Start-Process -FilePath $exe -ArgumentList @('-m', $model, '--alias', 'qwen/qwen3.8-27b', '-c', '32768', '-ngl', '99',
    '--parallel', '1', '--load-mode', 'none', '-ctk', 'q8_0', '-ctv', 'q8_0',
    '--spec-type', 'draft-mtp', '--spec-draft-n-max', '4', '--spec-draft-p-min', '0.75',
    '--jinja', '--chat-template-kwargs', '{\"reasoning_effort\":\"xhigh\"}',
    '--host', '127.0.0.1', '--port', '1234') -WindowStyle Hidden
$ok = $false
for ($i = 0; $i -lt 300; $i++) { Start-Sleep -Seconds 2
    try { $h = Invoke-RestMethod 'http://127.0.0.1:1234/health' -TimeoutSec 2; if ($h.status -eq 'ok') { $ok = $true; break } } catch {} }
if (-not $ok) { Write-Output 'SERVER FAILED'; exit 1 }
$env:LLAMA_SERVER = $exe
Set-Location E:\AI\benchmark
python bench.py --model $model --no-spawn --port 1234 --datasets GSM8K --samples 200 `
    --max-tokens 16384 --greedy --score 2>&1 | Select-Object -Last 12
$newest = Get-ChildItem E:\AI\benchmark\results\*.json | Sort-Object LastWriteTime -Descending | Select-Object -First 1
if ($newest) { Copy-Item $newest.FullName 'E:\AI\aider\qwen\gsm8k200-xhigh-16k.json' }
try { Get-Process llama-server -ErrorAction Stop | Stop-Process -Force -Confirm:$false } catch {}
Write-Output 'XHIGH 16K DONE'
