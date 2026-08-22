# Verify the newly-promoted serve-qwen.bat defaults under CURRENT desktop
# conditions: [1] IQ4_XS text-only -c 196608 and [3] IQ4_XS + vision -c 147456.
# Each gets a short temp-0 code probe AND a ~12k-token-deep prompt, plus VRAM sampling.
$ErrorActionPreference = 'Continue'
$exe = 'E:\AI\llama.cpp\llama-server.exe'
$model = 'C:\Users\chink\.lmstudio\models\unsloth\Qwen3.8-27B-GGUF\Qwen3.8-27B-UD-IQ4_XS.gguf'
$mmproj = 'C:\Users\chink\.lmstudio\models\lmstudio-community\Qwen3.8-27B-GGUF\mmproj-Qwen3.8-27B-BF16.gguf'
$code = 'Write a single self-contained JavaScript file implementing a red-black tree class with insert, delete, search and an in-order iterator. Code only, no explanation.'

# ~12k-token varied filler, built without string interpolation
$lines = New-Object System.Collections.Generic.List[string]
$lines.Add('Reference notes for the task below. Read them, then do the task at the end.')
for ($i = 1; $i -le 460; $i++) {
    $frag = [Convert]::ToString((($i * 48271) % 1048573), 16)
    $l = 'Note ' + $i + ': subsystem alpha-' + (($i * 7) % 97) + ' reported latency ' + ((17 * $i) % 993) + ' ms on shard ' + ($i % 13) + ', retry budget ' + ((3 * $i) % 29) + ', digest fragment ' + $frag + ', remark: threshold crossed only when the moving median over window ' + ((5 * $i) % 47) + ' exceeded baseline by ' + ((11 * $i) % 83) + ' percent.'
    $lines.Add($l)
}
$lines.Add('TASK: ' + $code)
$longPrompt = [string]::Join("`n", $lines)

function Stop-Server { try { Get-Process llama-server -ErrorAction Stop | Stop-Process -Force -Confirm:$false } catch {}; Start-Sleep -Seconds 3 }
function Send-Probe([string]$text) {
    $body = @{ model='qwen/qwen3.8-27b'; temperature=0; top_k=1; max_tokens=700
               messages=@(@{role='user';content=$text}) } | ConvertTo-Json -Depth 5
    $sw = [Diagnostics.Stopwatch]::StartNew()
    $r = Invoke-RestMethod -Uri 'http://127.0.0.1:1234/v1/chat/completions' -Method Post `
        -ContentType 'application/json' -Body ([Text.Encoding]::UTF8.GetBytes($body)) -TimeoutSec 0
    $sw.Stop()
    $res = @{}
    $res.tps = [math]::Round($r.usage.completion_tokens / $sw.Elapsed.TotalSeconds, 1)
    $res.ptok = $r.usage.prompt_tokens
    return $res
}

$cfgNames = @('[1] text-only -c 196608', '[3] vision -c 147456')
$cfgCtx   = @(196608, 147456)
for ($c = 0; $c -lt 2; $c++) {
    Stop-Server
    Write-Output ('===== ' + $cfgNames[$c] + ' - loading =====')
    $args_ = @('-m', $model, '--alias', 'qwen/qwen3.8-27b', '-c', $cfgCtx[$c], '-ngl', '99',
        '--parallel', '1', '--load-mode', 'none', '-ctk', 'q8_0', '-ctv', 'q8_0',
        '--spec-type', 'draft-mtp', '--spec-draft-n-max', '4', '--spec-draft-p-min', '0.75',
        '--jinja', '--host', '127.0.0.1', '--port', '1234')
    if ($c -eq 1) { $args_ += @('--mmproj', $mmproj, '--image-min-tokens', '1024') }
    Start-Process -FilePath $exe -ArgumentList $args_ -WindowStyle Hidden
    $ok = $false
    for ($i = 0; $i -lt 300; $i++) { Start-Sleep -Seconds 2
        try { $h = Invoke-RestMethod 'http://127.0.0.1:1234/health' -TimeoutSec 2; if ($h.status -eq 'ok') { $ok = $true; break } } catch {} }
    if (-not $ok) { Write-Output ($cfgNames[$c] + ': SERVER FAILED'); continue }
    $null = Send-Probe 'Say OK.'
    $p1 = Send-Probe $code
    Write-Output ('short probe : ' + $p1.tps + ' t/s  (prompt ' + $p1.ptok + ' tok)')
    $p2 = Send-Probe $longPrompt
    $mem = (nvidia-smi --query-gpu=memory.used --format=csv,noheader,nounits | Select-Object -First 1).Trim()
    $shMiB = 0
    $sh = Get-Counter '\GPU Process Memory(*)\Shared Usage' -ErrorAction SilentlyContinue
    if ($sh) { $shMiB = [math]::Round((($sh.CounterSamples | Measure-Object CookedValue -Sum).Sum) / 1MB) }
    Write-Output ('deep probe  : ' + $p2.tps + ' t/s  (prompt ' + $p2.ptok + ' tok = agent-session depth)')
    Write-Output ('vram after  : dedicated ' + $mem + ' MiB, total shared in use ' + $shMiB + ' MiB')
}
Stop-Server
Write-Output 'VERIFY RECOMMEND DONE'
