# Second pass of the reasoning-effort sweep: same prompt.md, same tuned config,
# fresh temp-1.0 sampling. Outputs '... - <effort> - pass2.txt/html' so pass 1
# stays intact. Gives two independent samples per effort for quality judging.
$ErrorActionPreference = 'Stop'
$dir       = 'E:\AI\aider\qwen'
$modelName = 'Qwen3.8-27B-Q4_K_M'
$prompt    = Get-Content -Raw (Join-Path $dir 'prompt.md')
$summary   = @()

function Stop-Server {
    try { Get-Process llama-server -ErrorAction Stop | Stop-Process -Force -Confirm:$false } catch {}
    Start-Sleep -Seconds 3
}

foreach ($e in @('low', 'medium', 'xhigh')) {
    Stop-Server
    Write-Output "[$e pass2] starting server..."
    Start-Process -FilePath 'E:\AI\aider\serve-qwen.bat' -ArgumentList @($e, 122880) -WindowStyle Minimized
    $ok = $false
    for ($i = 0; $i -lt 600; $i++) {
        Start-Sleep -Seconds 2
        try { $h = Invoke-RestMethod 'http://127.0.0.1:1234/health' -TimeoutSec 2; if ($h.status -eq 'ok') { $ok = $true; break } } catch {}
    }
    if (-not $ok) { Write-Output "[$e pass2] SERVER FAILED"; continue }
    $body = @{ model='qwen/qwen3.8-27b'; messages=@(@{role='user';content=$prompt.ToString()}) } | ConvertTo-Json -Depth 5
    $sw = [Diagnostics.Stopwatch]::StartNew()
    $resp = Invoke-RestMethod -Uri 'http://127.0.0.1:1234/v1/chat/completions' -Method Post `
        -ContentType 'application/json; charset=utf-8' -Headers @{Authorization='Bearer dummy'} `
        -Body ([Text.Encoding]::UTF8.GetBytes($body)) -TimeoutSec 0
    $sw.Stop()
    $msg = $resp.choices[0].message
    $out = ''
    if ($msg.reasoning_content) { $out += "===== THINKING =====`r`n$($msg.reasoning_content)`r`n`r`n===== ANSWER =====`r`n" }
    $out += $msg.content
    [IO.File]::WriteAllText((Join-Path $dir "$modelName - $e - pass2.txt"), $out, [Text.UTF8Encoding]::new($false))
    $u = $resp.usage
    $tps = [math]::Round($u.completion_tokens / $sw.Elapsed.TotalSeconds, 1)
    $line = '{0,-7} pass2  completion={1,6} tokens  wall={2:hh\:mm\:ss}  ~{3} t/s  finish={4}' -f `
        $e, $u.completion_tokens, $sw.Elapsed, $tps, $resp.choices[0].finish_reason
    $summary += $line
    Write-Output "[$e pass2] done: $line"
}
Stop-Server
& powershell -NoProfile -ExecutionPolicy Bypass -File (Join-Path $dir 'extract-html.ps1')
$summary | Add-Content (Join-Path $dir 'sweep-summary.txt') -Encoding UTF8
Write-Output 'SWEEP PASS2 DONE'
