# Sweep serve-qwen.bat across reasoning efforts low/medium/xhigh with the same
# prompt, saving all generated tokens (thinking + answer) per effort level.
$ErrorActionPreference = 'Stop'
$dir       = 'E:\AI\aider\qwen'
$modelName = 'Qwen3.8-27B-Q4_K_M'
$prompt    = Get-Content -Raw (Join-Path $dir 'prompt.md')
$efforts   = @('low', 'medium', 'xhigh')
$summary   = @()

foreach ($e in $efforts) {
    try { Get-Process llama-server -ErrorAction Stop | Stop-Process -Force -Confirm:$false } catch {}
    Start-Sleep -Seconds 3

    Write-Output "[$e] starting server..."
    Start-Process -FilePath 'E:\AI\aider\serve-qwen.bat' -ArgumentList $e -WindowStyle Minimized

    # --load-mode none makes loading slow; poll health up to 20 min
    $ok = $false
    for ($i = 0; $i -lt 600; $i++) {
        Start-Sleep -Seconds 2
        try {
            $h = Invoke-RestMethod 'http://127.0.0.1:1234/health' -TimeoutSec 2
            if ($h.status -eq 'ok') { $ok = $true; break }
        } catch {}
    }
    if (-not $ok) { throw "[$e] server never became healthy" }
    Write-Output "[$e] server up, sending prompt..."

    $body = @{ model = 'qwen/qwen3.8-27b'
               messages = @(@{ role = 'user'; content = $prompt.ToString() }) } | ConvertTo-Json -Depth 5
    $sw = [Diagnostics.Stopwatch]::StartNew()
    $resp = Invoke-RestMethod -Uri 'http://127.0.0.1:1234/v1/chat/completions' `
        -Method Post -ContentType 'application/json; charset=utf-8' `
        -Headers @{ Authorization = 'Bearer dummy' } `
        -Body ([Text.Encoding]::UTF8.GetBytes($body)) -TimeoutSec 0
    $sw.Stop()

    $msg = $resp.choices[0].message
    $out = ''
    if ($msg.reasoning_content) {
        $out += "===== THINKING =====`r`n$($msg.reasoning_content)`r`n`r`n===== ANSWER =====`r`n"
    }
    $out += $msg.content
    $file = Join-Path $dir "$modelName - $e.txt"
    [IO.File]::WriteAllText($file, $out, [Text.UTF8Encoding]::new($false))

    $u = $resp.usage
    $tps = [math]::Round($u.completion_tokens / $sw.Elapsed.TotalSeconds, 1)
    $line = '{0,-7} completion={1,6} tokens  prompt={2} tokens  wall={3:hh\:mm\:ss}  ~{4} t/s  finish={5}' -f `
        $e, $u.completion_tokens, $u.prompt_tokens, $sw.Elapsed, $tps, $resp.choices[0].finish_reason
    $summary += $line
    Write-Output "[$e] done: $line"
}

try { Get-Process llama-server -ErrorAction Stop | Stop-Process -Force -Confirm:$false } catch {}
$summary | Set-Content (Join-Path $dir 'sweep-summary.txt') -Encoding utf8
Write-Output 'SWEEP DONE'
