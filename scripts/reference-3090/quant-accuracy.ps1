# Stronger quant comparison for the guide: GSM8K n=200, greedy, scored, paired
# (same deterministic prompt selection across models via bench.py).
# MTP speculation is enabled for speed only - lossless, scores unaffected.
$ErrorActionPreference = 'Continue'
$env:LLAMA_SERVER = 'E:\AI\llama.cpp\llama-server.exe'
try { Get-Process llama-server -ErrorAction Stop | Stop-Process -Force -Confirm:$false } catch {}

$models = @(
    'C:\Users\chink\.lmstudio\models\lmstudio-community\Qwen3.8-27B-GGUF\Qwen3.8-27B-Q4_K_M.gguf',
    'C:\Users\chink\.lmstudio\models\esatapedico\Qwen3.8-27B-NVFP4-MTP-GGUF\Qwen3.8-27B-NVFP4-MTP-HIGH.gguf',
    'C:\Users\chink\.lmstudio\models\esatapedico\Qwen3.8-27B-NVFP4-MTP-GGUF\Qwen3.8-27B-NVFP4-MTP-VERY-LOW.gguf'
)
$xl = 'C:\Users\chink\.lmstudio\models\unsloth\Qwen3.8-27B-GGUF\Qwen3.8-27B-UD-Q4_K_XL.gguf'
# include UD-Q4_K_XL only if the overnight download finished (full ~17.6 GB file)
if ((Test-Path $xl) -and ((Get-Item $xl).Length -gt 16GB)) { $models += $xl }

Set-Location E:\AI\benchmark
python bench.py --model ($models -join ',') --datasets GSM8K --samples 200 --max-tokens 4096 --greedy --score `
    --server-args "--spec-type draft-mtp --spec-draft-n-max 4 --spec-draft-p-min 0.75" 2>&1 |
    Select-Object -Last 40
Write-Output "MODELS TESTED: $($models.Count) (XL included: $($models -contains $xl))"
Write-Output 'QUANT ACCURACY DONE'
