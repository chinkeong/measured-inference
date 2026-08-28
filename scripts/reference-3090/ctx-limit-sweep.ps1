# Ground-truth context-size ceiling on 24 GB VRAM: increase -c until the
# spill tipping point, then binary-refine to 4096-token resolution.
# Uses serve-qwen.bat (current tuned flags: -ngl 99, MTP n4 p0.75, q8 KV, mmproj).
# Spill detection: temp-0 code probe t/s dropping >25% below the 122880 reference,
# or the server failing to load. Run this only when nothing else uses the GPU.
. (Join-Path $PSScriptRoot "..\gpu-lock.ps1")
$ErrorActionPreference = 'Stop'
$dir = 'E:\AI\aider\qwen'
$probeText = 'Write a single self-contained JavaScript file implementing a red-black tree class with insert, delete, search and an in-order iterator. Code only, no explanation.'
$log = @()

function Stop-Server {
    try { Get-Process llama-server -ErrorAction Stop | Stop-Process -Force -Confirm:$false } catch {}
    Start-Sleep -Seconds 3
}

function Probe-Ctx([int]$ctx) {
    # returns t/s, 0 if the server failed to come up (treat as over the limit).
    # Write-Host (not Write-Output) inside this function - Output pollutes the return value.
    Stop-Server
    Write-Host "[ctx $ctx] loading..."
    Start-GuardedServer -FilePath 'E:\AI\aider\serve-qwen.bat' -ArgumentList @('low', $ctx) -WindowStyle Minimized
    $ok = $false
    for ($i = 0; $i -lt 300; $i++) {
        Start-Sleep -Seconds 2
        try {
            $h = Invoke-RestMethod 'http://127.0.0.1:1234/health' -TimeoutSec 2
            if ($h.status -eq 'ok') { $ok = $true; break }
        } catch {}
        if (-not (Get-Process llama-server -ErrorAction SilentlyContinue)) { break }
    }
    if (-not $ok) { Write-Host "[ctx $ctx] FAILED TO LOAD"; $script:log += "ctx=$ctx  load FAILED"; return 0 }
    $body = @{ model='qwen/qwen3.8-27b'; temperature=0; top_k=1; max_tokens=400
               messages=@(@{role='user';content=$probeText}) } | ConvertTo-Json -Depth 5
    $sw = [Diagnostics.Stopwatch]::StartNew()
    $resp = Invoke-RestMethod -Uri 'http://127.0.0.1:1234/v1/chat/completions' -Method Post `
        -ContentType 'application/json' -Headers @{Authorization='Bearer dummy'} `
        -Body ([Text.Encoding]::UTF8.GetBytes($body)) -TimeoutSec 0
    $sw.Stop()
    $tps = [math]::Round($resp.usage.completion_tokens / $sw.Elapsed.TotalSeconds, 1)
    $mem = ((nvidia-smi --query-gpu=memory.used --format=csv,noheader,nounits) | Select-Object -First 1).Trim()
    Write-Host "[ctx $ctx] $tps t/s, dedicated VRAM used ${mem} MiB"
    $script:log += "ctx=$ctx  $tps t/s  vram=${mem}MiB"
    return [double]$tps
}

$MAXC = 262144   # native limit
$refTps = Probe-Ctx 122880
if ($refTps -eq 0) { throw 'reference ctx 122880 failed to load - GPU not free?' }
$floor = [math]::Round($refTps * 0.75, 1)
Write-Output "[ref] 122880 = $refTps t/s; spill floor = $floor t/s"

# expand upward in 8192 steps until tipping
$good = 122880
$bad = 0
$c = 122880
while ($true) {
    $c = [math]::Min($c + 8192, $MAXC)
    $t = Probe-Ctx $c
    if ($t -ge $floor) {
        $good = $c
        if ($c -ge $MAXC) { break }
    } else { $bad = $c; break }
}

# binary refine between good and bad at 4096 resolution
if ($bad -gt 0) {
    while (($bad - $good) -gt 4096) {
        $mid = [int]([math]::Floor((($good + $bad) / 2) / 4096) * 4096)
        if ($mid -le $good -or $mid -ge $bad) { break }
        if ((Probe-Ctx $mid) -ge $floor) { $good = $mid } else { $bad = $mid }
    }
}

Stop-Server
$result = @("GROUND-TRUTH CONTEXT CEILING (this desktop state, current serve-qwen.bat flags):",
            "largest spill-free context: $good",
            ($(if ($bad -gt 0) { "first degraded/failed context: $bad" } else { "native max $MAXC reached without spill" })),
            "reference: 122880 = $refTps t/s, floor = $floor t/s", "", "probe log:") + $log
$result | Set-Content (Join-Path $dir 'ctx-limit-result.txt') -Encoding utf8
$result | ForEach-Object { Write-Output $_ }
Write-Output 'CTX LIMIT SWEEP DONE'
