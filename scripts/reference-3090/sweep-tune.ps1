# Find the LARGEST context (4096-token resolution) that decodes fast under the
# current desktop VRAM load, then rerun the low/medium/xhigh effort sweep there.
. (Join-Path $PSScriptRoot "..\gpu-lock.ps1")
$ErrorActionPreference = 'Stop'
$dir       = 'E:\AI\aider\qwen'
$modelName = 'Qwen3.8-27B-Q4_K_M'
$prompt    = Get-Content -Raw (Join-Path $dir 'prompt.md')
$targetTps = 40          # healthy temp-0 essay probe with MTP measures ~43 t/s
                         # (2026-08-22, -ngl 99); spill signature is ~30 or less
$probeText = 'Write a detailed 500-word technical explanation of how a marine aquarium nitrogen cycle works.'
$probeLog  = @()

function Stop-Server {
    try { Get-Process llama-server -ErrorAction Stop | Stop-Process -Force -Confirm:$false } catch {}
    Start-Sleep -Seconds 3
}

function Start-Server([string]$effort, [int]$ctx) {
    Stop-Server
    Start-GuardedServer -FilePath 'E:\AI\aider\serve-qwen.bat' -ArgumentList @($effort, $ctx) -WindowStyle Minimized
    for ($i = 0; $i -lt 600; $i++) {
        Start-Sleep -Seconds 2
        try {
            $h = Invoke-RestMethod 'http://127.0.0.1:1234/health' -TimeoutSec 2
            if ($h.status -eq 'ok') { return }
        } catch {}
    }
    throw "server never became healthy (effort=$effort ctx=$ctx)"
}

function Send-Chat([string]$text, $maxTokens, $temp) {
    $m = @{ role = 'user'; content = $text.ToString() }
    $b = @{ model = 'qwen/qwen3.8-27b'; messages = @($m) }
    if ($maxTokens) { $b.max_tokens = $maxTokens }
    if ($null -ne $temp) { $b.temperature = $temp; $b.top_k = 1 }
    $json = $b | ConvertTo-Json -Depth 5
    $sw = [Diagnostics.Stopwatch]::StartNew()
    $resp = Invoke-RestMethod -Uri 'http://127.0.0.1:1234/v1/chat/completions' `
        -Method Post -ContentType 'application/json; charset=utf-8' `
        -Headers @{ Authorization = 'Bearer dummy' } `
        -Body ([Text.Encoding]::UTF8.GetBytes($json)) -TimeoutSec 0
    $sw.Stop()
    return @{ resp = $resp; secs = $sw.Elapsed.TotalSeconds; elapsed = $sw.Elapsed }
}

# Probes run at temp 0 (greedy) so speeds are comparable to the 81.7 t/s tuning
# benchmark: healthy = ~75-82 t/s, spill = ~30. Write-Host, not Write-Output,
# so the log lines don't pollute the function's return value.
function Probe([int]$ctx) {
    Write-Host "[probe] ctx=$ctx loading..."
    Start-Server 'low' $ctx
    [void](Send-Chat 'Say OK.' 16 $null)   # warmup
    $r = Send-Chat $probeText 700 0
    $tps = [math]::Round($r.resp.usage.completion_tokens / $r.secs, 1)
    $line = "ctx=$ctx  probe(temp0): $($r.resp.usage.completion_tokens) tok in $([math]::Round($r.secs,1))s = $tps t/s"
    $script:probeLog += $line
    Write-Host "[probe] $line"
    return $tps
}

# ---- Phase 1: find the largest fast context, 4096 resolution
$MAXC = 122880
$good = 0                      # largest ctx confirmed fast
$bad  = $MAXC + 4096           # smallest ctx confirmed slow (sentinel above max)

if ((Probe $MAXC) -ge $targetTps) {
    $good = $MAXC              # full context is fast (VRAM freed up) - done
} else {
    $bad = $MAXC
    foreach ($c in @(98304, 81920, 65536, 49152)) {
        if ((Probe $c) -ge $targetTps) { $good = $c; break } else { $bad = $c }
    }
    if ($good -gt 0) {
        while (($bad - $good) -gt 4096) {
            $mid = [int]([math]::Floor((($good + $bad) / 2) / 4096) * 4096)
            if ($mid -le $good -or $mid -ge $bad) { break }
            if ((Probe $mid) -ge $targetTps) { $good = $mid } else { $bad = $mid }
        }
    }
}
if ($good -eq 0) {
    $good = 49152
    Write-Output "[probe] nothing hit $targetTps t/s - GPU is loaded by other apps; falling back to ctx=$good"
}
Write-Output "[probe] CHOSEN ctx=$good (largest fast context at 4096 resolution)"

# ---- Phase 2: full effort sweep at the chosen context
$summary = @("context: $good (probe results below)") + $probeLog + ''
foreach ($e in @('low', 'medium', 'xhigh')) {
    Write-Output "[$e] starting server (ctx=$good)..."
    Start-Server $e $good
    Write-Output "[$e] server up, sending prompt..."
    $r = Send-Chat $prompt $null
    $msg = $r.resp.choices[0].message
    $out = ''
    if ($msg.reasoning_content) {
        $out += "===== THINKING =====`r`n$($msg.reasoning_content)`r`n`r`n===== ANSWER =====`r`n"
    }
    $out += $msg.content
    [IO.File]::WriteAllText((Join-Path $dir "$modelName - $e.txt"), $out, [Text.UTF8Encoding]::new($false))
    $u = $r.resp.usage
    $tps = [math]::Round($u.completion_tokens / $r.secs, 1)
    $line = '{0,-7} completion={1,6} tokens  prompt={2} tokens  wall={3:hh\:mm\:ss}  ~{4} t/s  finish={5}' -f `
        $e, $u.completion_tokens, $u.prompt_tokens, $r.elapsed, $tps, $r.resp.choices[0].finish_reason
    $summary += $line
    Write-Output "[$e] done: $line"
}

Stop-Server
$summary | Set-Content (Join-Path $dir 'sweep-summary.txt') -Encoding utf8
Write-Output 'SWEEP DONE'
