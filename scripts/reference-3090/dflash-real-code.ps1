# The missing apples-to-apples: DFlash2 on the SAME realistic code probe that
# measured MTP's 57.9 t/s (n-max 4, p-min 0.75). Uses the PR-27342 build.
. (Join-Path $PSScriptRoot "..\gpu-lock.ps1")
$ErrorActionPreference = 'Continue'
$server = 'E:\AI\llama.cpp-dflash\build\bin\llama-server.exe'
$model  = 'C:\Users\chink\.lmstudio\models\lmstudio-community\Qwen3.8-27B-GGUF\Qwen3.8-27B-Q4_K_M.gguf'
$draft  = 'C:\Users\chink\.lmstudio\models\incoai\Qwen3.8-27B-DFlash2-GGUF\Qwen3.8-27B-DFlash2-Q4_K_M.gguf'
$probe  = 'Write a single self-contained JavaScript file implementing a red-black tree class with insert, delete, search and an in-order iterator. Code only, no explanation.'
if (-not (Test-Path $server)) { Write-Output 'DFLASH BUILD MISSING - skip'; exit 0 }
if (-not (Test-Path $draft))  { Write-Output 'DFLASH DRAFTER MISSING - skip'; exit 0 }

$configs = @(
    @(),                                                              # build's own no-spec baseline
    @('-md', $draft, '--spec-type', 'draft-dflash', '--spec-draft-n-max', '2'),
    @('-md', $draft, '--spec-type', 'draft-dflash', '--spec-draft-n-max', '4'),
    @('-md', $draft, '--spec-type', 'draft-dflash', '--spec-draft-n-max', '6'),
    @('-md', $draft, '--spec-type', 'draft-dflash', '--spec-draft-n-max', '4', '--spec-draft-p-min', '0.75')
)
foreach ($cfg in $configs) {
    try { Get-Process llama-server -ErrorAction Stop | Stop-Process -Force -Confirm:$false } catch {}
    Start-Sleep -Seconds 3
    $label = if ($cfg.Count -eq 0) { 'dflash-build baseline (no spec)' } else { ($cfg | Where-Object { $_ -notmatch '^C:' }) -join ' ' }
    Write-Output "===== $label ====="
    $args_ = @('-m', $model, '--alias', 'qwen/qwen3.8-27b', '-c', '32768', '-ngl', '99',
        '--parallel', '1', '-ctk', 'q8_0', '-ctv', 'q8_0', '--jinja',
        '--host', '127.0.0.1', '--port', '1234') + $cfg
    $err = "E:\AI\aider\qwen\dflash-$([math]::Abs($label.GetHashCode())).log"
    Start-GuardedServer -FilePath $server -ArgumentList $args_ -WindowStyle Hidden -RedirectStandardError $err
    $ok = $false
    for ($i = 0; $i -lt 300; $i++) {
        Start-Sleep -Seconds 2
        try { $h = Invoke-RestMethod 'http://127.0.0.1:1234/health' -TimeoutSec 2; if ($h.status -eq 'ok') { $ok = $true; break } } catch {}
    }
    if (-not $ok) { Write-Output "[$label] SERVER FAILED"; continue }
    $body = @{ model='qwen/qwen3.8-27b'; temperature=0; top_k=1; max_tokens=700
               messages=@(@{role='user';content=$probe}) } | ConvertTo-Json -Depth 5
    [void](Invoke-RestMethod -Uri 'http://127.0.0.1:1234/v1/chat/completions' -Method Post -ContentType 'application/json' -Body ([Text.Encoding]::UTF8.GetBytes('{"model":"qwen/qwen3.8-27b","max_tokens":16,"messages":[{"role":"user","content":"Say OK."}]')) -TimeoutSec 0)
    $sw = [Diagnostics.Stopwatch]::StartNew()
    $resp = Invoke-RestMethod -Uri 'http://127.0.0.1:1234/v1/chat/completions' -Method Post -ContentType 'application/json' -Body ([Text.Encoding]::UTF8.GetBytes($body)) -TimeoutSec 0
    $sw.Stop()
    $tps = [math]::Round($resp.usage.completion_tokens / $sw.Elapsed.TotalSeconds, 1)
    Write-Output "RESULT [$label]: $($resp.usage.completion_tokens) tok in $([math]::Round($sw.Elapsed.TotalSeconds,1))s = $tps t/s"
    Start-Sleep -Seconds 2
    Get-Content $err -ErrorAction SilentlyContinue | Select-String -Pattern 'draft acceptance' | Select-Object -Last 1 | ForEach-Object { $_.Line }
}
try { Get-Process llama-server -ErrorAction Stop | Stop-Process -Force -Confirm:$false } catch {}
Write-Output 'DFLASH REAL CODE DONE'
