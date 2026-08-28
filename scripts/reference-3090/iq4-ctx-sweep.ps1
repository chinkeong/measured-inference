# Ground-truth context ceiling for UD-IQ4_XS (13.3 GiB vs Q4_K_M's 15.4).
# Q4_K_M measured ~131k resident / ~213k shallow; the 2.1 GiB saving predicts
# ~+63k on both. Verify: reference at 122880, jump to predicted region, refine.
. (Join-Path $PSScriptRoot "..\gpu-lock.ps1")
$ErrorActionPreference = 'Stop'
$dir = 'E:\AI\aider\qwen'
$exe = 'E:\AI\llama.cpp\llama-server.exe'
$model = 'C:\Users\chink\.lmstudio\models\unsloth\Qwen3.8-27B-GGUF\Qwen3.8-27B-UD-IQ4_XS.gguf'
$mmproj = 'C:\Users\chink\.lmstudio\models\lmstudio-community\Qwen3.8-27B-GGUF\mmproj-Qwen3.8-27B-BF16.gguf'
$probeText = 'Write a single self-contained JavaScript file implementing a red-black tree class with insert, delete, search and an in-order iterator. Code only, no explanation.'
$log = @()

function Stop-Server {
    try { Get-Process llama-server -ErrorAction Stop | Stop-Process -Force -Confirm:$false } catch {}
    Start-Sleep -Seconds 3
}
function Probe-Ctx([int]$ctx) {
    Stop-Server
    Write-Host "[ctx $ctx] loading..."
    $args_ = @('-m', $model, '--mmproj', $mmproj, '--alias', 'qwen/qwen3.8-27b',
        '-c', $ctx, '-ngl', '99', '--parallel', '1', '--load-mode', 'none',
        '-ctk', 'q8_0', '-ctv', 'q8_0',
        '--spec-type', 'draft-mtp', '--spec-draft-n-max', '4', '--spec-draft-p-min', '0.75',
        '--jinja', '--host', '127.0.0.1', '--port', '1234')
    Start-GuardedServer -FilePath $exe -ArgumentList $args_ -WindowStyle Hidden
    $ok = $false
    for ($i = 0; $i -lt 300; $i++) {
        Start-Sleep -Seconds 2
        try { $h = Invoke-RestMethod 'http://127.0.0.1:1234/health' -TimeoutSec 2; if ($h.status -eq 'ok') { $ok = $true; break } } catch {}
        if (-not (Get-Process llama-server -ErrorAction SilentlyContinue)) { break }
    }
    if (-not $ok) { Write-Host "[ctx $ctx] FAILED TO LOAD"; $script:log += "ctx=$ctx  load FAILED"; return [double]0 }
    $body = @{ model='qwen/qwen3.8-27b'; temperature=0; top_k=1; max_tokens=400
               messages=@(@{role='user';content=$probeText}) } | ConvertTo-Json -Depth 5
    $sw = [Diagnostics.Stopwatch]::StartNew()
    $resp = Invoke-RestMethod -Uri 'http://127.0.0.1:1234/v1/chat/completions' -Method Post `
        -ContentType 'application/json' -Body ([Text.Encoding]::UTF8.GetBytes($body)) -TimeoutSec 0
    $sw.Stop()
    $tps = [math]::Round($resp.usage.completion_tokens / $sw.Elapsed.TotalSeconds, 1)
    $mem = ((nvidia-smi --query-gpu=memory.used --format=csv,noheader,nounits) | Select-Object -First 1).Trim()
    Write-Host "[ctx $ctx] $tps t/s, dedicated VRAM ${mem} MiB"
    $script:log += "ctx=$ctx  $tps t/s  vram=${mem}MiB"
    return [double]$tps
}

$MAXC = 262144
$refTps = Probe-Ctx 122880
if ($refTps -eq 0) { throw 'reference failed to load' }
$floor = [math]::Round($refTps * 0.75, 1)
Write-Host "[ref] 122880 = $refTps t/s; floor = $floor"

$good = 122880
$bad = 0
$c = 180224   # jump near the predicted new territory, then walk up
while ($true) {
    $t = Probe-Ctx $c
    if ($t -ge $floor) {
        $good = $c
        if ($c -ge $MAXC) { break }
        $c = [math]::Min($c + 16384, $MAXC)
    } else { $bad = $c; break }
}
if ($bad -gt 0) {
    while (($bad - $good) -gt 4096) {
        $mid = [int]([math]::Floor((($good + $bad) / 2) / 4096) * 4096)
        if ($mid -le $good -or $mid -ge $bad) { break }
        if ((Probe-Ctx $mid) -ge $floor) { $good = $mid } else { $bad = $mid }
    }
}
Stop-Server
$result = @("IQ4_XS CONTEXT CEILING (shallow-probe, mmproj loaded, tuned MTP):",
            "largest fast context: $good",
            ($(if ($bad -gt 0) { "first degraded/failed: $bad" } else { "native max reached without degradation" })),
            "reference: 122880 = $refTps t/s, floor = $floor", "", "probe log:") + $log
$result | Set-Content (Join-Path $dir 'iq4-ctx-result.txt') -Encoding utf8
$result | ForEach-Object { Write-Output $_ }
Write-Output 'IQ4 CTX SWEEP DONE'
