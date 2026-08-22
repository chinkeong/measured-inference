# Final gate for UD-IQ4_XS: n=200 GSM8K end-to-end (template, tool path, accuracy).
$ErrorActionPreference = 'Continue'
$env:LLAMA_SERVER = 'E:\AI\llama.cpp\llama-server.exe'
try { Get-Process llama-server -ErrorAction Stop | Stop-Process -Force -Confirm:$false } catch {}
Set-Location E:\AI\benchmark
python bench.py --model 'C:\Users\chink\.lmstudio\models\unsloth\Qwen3.8-27B-GGUF\Qwen3.8-27B-UD-IQ4_XS.gguf' `
    --datasets GSM8K --samples 200 --max-tokens 4096 --greedy --score `
    --server-args "--spec-type draft-mtp --spec-draft-n-max 4 --spec-draft-p-min 0.75" 2>&1 |
    Select-Object -Last 12
Write-Output 'IQ4 ACCURACY DONE'
