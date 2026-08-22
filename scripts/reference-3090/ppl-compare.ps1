# Perplexity comparison of the three local quants on wikitext-2-raw.
# Per-token statistics resolve Q4-class quality differences that n<1000
# accuracy benchmarks cannot (each PPL run scores ~300k token positions).
$ErrorActionPreference = 'Continue'
$dir = 'E:\AI\aider\qwen'
$corpus = Join-Path $dir 'wiki.test.raw'

if (-not (Test-Path $corpus)) {
    $zip = Join-Path $dir 'wikitext-2-raw-v1.zip'
    Invoke-WebRequest 'https://huggingface.co/datasets/ggml-org/ci/resolve/main/wikitext-2-raw-v1.zip' -OutFile $zip
    Expand-Archive $zip -DestinationPath $dir -Force
    $raw = Get-ChildItem $dir -Recurse -Filter 'wiki.test.raw' | Select-Object -First 1
    if ($raw -and $raw.FullName -ne $corpus) { Copy-Item $raw.FullName $corpus }
}
if (-not (Test-Path $corpus)) { Write-Output 'FATAL: corpus download failed'; exit 1 }

try { Get-Process llama-server -ErrorAction Stop | Stop-Process -Force -Confirm:$false } catch {}

$models = @(
    @('Q4_K_M',         'C:\Users\chink\.lmstudio\models\lmstudio-community\Qwen3.8-27B-GGUF\Qwen3.8-27B-Q4_K_M.gguf'),
    @('NVFP4-HIGH',     'C:\Users\chink\.lmstudio\models\esatapedico\Qwen3.8-27B-NVFP4-MTP-GGUF\Qwen3.8-27B-NVFP4-MTP-HIGH.gguf'),
    @('NVFP4-VERY-LOW', 'C:\Users\chink\.lmstudio\models\esatapedico\Qwen3.8-27B-NVFP4-MTP-GGUF\Qwen3.8-27B-NVFP4-MTP-VERY-LOW.gguf')
)
$xl = 'C:\Users\chink\.lmstudio\models\unsloth\Qwen3.8-27B-GGUF\Qwen3.8-27B-UD-Q4_K_XL.gguf'
if ((Test-Path $xl) -and ((Get-Item $xl).Length -gt 16GB)) { $models += ,@('UD-Q4_K_XL', $xl) }
$c1 = 'C:\Users\chink\.lmstudio\models\unsloth\Qwen3.8-27B-GGUF\Qwen3.8-27B-UD-IQ4_XS.gguf'
if ((Test-Path $c1) -and ((Get-Item $c1).Length -gt 13GB)) { $models += ,@('UD-IQ4_XS', $c1) }
$c2 = 'C:\Users\chink\.lmstudio\models\unsloth\Qwen3.8-27B-GGUF\Qwen3.8-27B-UD-Q4_K_M.gguf'
if ((Test-Path $c2) -and ((Get-Item $c2).Length -gt 15GB)) { $models += ,@('UD-Q4_K_M', $c2) }
$summary = @()
foreach ($m in $models) {
    $existing = Join-Path $dir "ppl-$($m[0]).log"
    if ((Test-Path $existing) -and (Select-String -Path $existing -Pattern 'Final estimate' -Quiet)) {
        $done = (Select-String -Path $existing -Pattern 'Final estimate' | Select-Object -Last 1).Line
        Write-Output "===== PPL: $($m[0]) (already done) ====="
        Write-Output "RESULT $($m[0]): $done"
        $summary += "$($m[0]): $done"
        continue
    }
    Write-Output "===== PPL: $($m[0]) ====="
    $out = & E:\AI\llama.cpp\llama-perplexity.exe -m $m[1] -f $corpus -ngl 99 -c 8192 2>&1 | Out-String
    $final = ($out -split "`n" | Select-String -Pattern 'Final estimate|PPL =' | Select-Object -Last 1)
    Write-Output "RESULT $($m[0]): $final"
    $summary += "$($m[0]): $final"
    $out | Set-Content (Join-Path $dir "ppl-$($m[0]).log") -Encoding utf8
    $summary | Set-Content (Join-Path $dir 'ppl-summary.txt') -Encoding utf8
}
$summary | Set-Content (Join-Path $dir 'ppl-summary.txt') -Encoding utf8
Write-Output 'PPL COMPARE DONE'
