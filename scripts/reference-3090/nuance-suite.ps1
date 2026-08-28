# Nuance suite: (1) depth/prefill series, (2) q8 KV quality PPL, (3) --parallel 2,
# (4) multi-image vision. Sequential; one log; ~40-50 min.
. (Join-Path $PSScriptRoot "..\gpu-lock.ps1")
$ErrorActionPreference = 'Continue'
$exe = 'E:\AI\llama.cpp\llama-server.exe'
$iq4 = 'C:\Users\chink\.lmstudio\models\unsloth\Qwen3.8-27B-GGUF\Qwen3.8-27B-UD-IQ4_XS.gguf'
$q4km = 'C:\Users\chink\.lmstudio\models\lmstudio-community\Qwen3.8-27B-GGUF\Qwen3.8-27B-Q4_K_M.gguf'
$mmproj = 'C:\Users\chink\.lmstudio\models\lmstudio-community\Qwen3.8-27B-GGUF\mmproj-Qwen3.8-27B-BF16.gguf'
$code = 'Write a single self-contained JavaScript file implementing a red-black tree class with insert, delete, search and an in-order iterator. Code only, no explanation.'

function Stop-Server { try { Get-Process llama-server -ErrorAction Stop | Stop-Process -Force -Confirm:$false } catch {}; Start-Sleep -Seconds 3 }
function Wait-Health { for ($i = 0; $i -lt 300; $i++) { Start-Sleep -Seconds 2
    try { $h = Invoke-RestMethod 'http://127.0.0.1:1234/health' -TimeoutSec 2; if ($h.status -eq 'ok') { return $true } } catch {} }
  return $false }
function Filler([int]$n) {
  $ls = New-Object System.Collections.Generic.List[string]
  for ($i = 1; $i -le $n; $i++) {
    $frag = [Convert]::ToString((($i * 48271) % 1048573), 16)
    $ls.Add('Note ' + $i + ': subsystem alpha-' + (($i * 7) % 97) + ' reported latency ' + ((17 * $i) % 993) + ' ms on shard ' + ($i % 13) + ', retry budget ' + ((3 * $i) % 29) + ', digest fragment ' + $frag + ', remark: threshold crossed only when the moving median over window ' + ((5 * $i) % 47) + ' exceeded baseline by ' + ((11 * $i) % 83) + ' percent.')
  }
  return [string]::Join("`n", $ls)
}

Write-Output '===== PART 1: depth/prefill series (IQ4_XS text-only -c 122880) ====='
Stop-Server
Start-GuardedServer -FilePath $exe -ArgumentList @('-m', $iq4, '--alias', 'q', '-c', '122880', '-ngl', '99',
    '--parallel', '1', '--load-mode', 'none', '-ctk', 'q8_0', '-ctv', 'q8_0',
    '--spec-type', 'draft-mtp', '--spec-draft-n-max', '4', '--spec-draft-p-min', '0.75',
    '--jinja', '--host', '127.0.0.1', '--port', '1234') -WindowStyle Hidden
if (-not (Wait-Health)) { Write-Output 'P1 SERVER FAILED' } else {
  foreach ($n in @(60, 220, 460, 925, 1400, 1850)) {
    $prompt = 'Read these notes, then do the task at the end.' + "`n" + (Filler $n) + "`nTASK: " + $code
    $body = @{ model='q'; temperature=0; top_k=1; max_tokens=400
               messages=@(@{role='user';content=$prompt}) } | ConvertTo-Json -Depth 5
    $r = Invoke-RestMethod -Uri 'http://127.0.0.1:1234/v1/chat/completions' -Method Post `
        -ContentType 'application/json' -Body ([Text.Encoding]::UTF8.GetBytes($body)) -TimeoutSec 0
    $t = $r.timings
    $acc = ''
    if ($t.draft_n) { $acc = '  accept=' + [math]::Round($t.draft_n_accepted / $t.draft_n, 2) }
    Write-Output ('depth ' + $t.prompt_n + ' tok: prefill ' + [math]::Round($t.prompt_per_second, 0) + ' t/s (' + [math]::Round($t.prompt_ms/1000, 1) + ' s), decode ' + [math]::Round($t.predicted_per_second, 1) + ' t/s' + $acc)
  }
}

Write-Output '===== PART 2: q8 KV quality (PPL vs cached fp16-KV 6.5348) ====='
Stop-Server
$out = & E:\AI\llama.cpp\llama-perplexity.exe -m $q4km -f E:\AI\aider\qwen\wiki.test.raw -ngl 99 -c 8192 -ctk q8_0 -ctv q8_0 -fa on 2>&1 | Out-String
$fin = ($out -split "`n" | Select-String -Pattern 'Final estimate' | Select-Object -Last 1)
Write-Output ('q8_0 KV: ' + $fin)
Write-Output 'fp16 KV (cached): Final estimate: PPL = 6.5348 +/- 0.04382'

Write-Output '===== PART 3: --parallel 2 (IQ4_XS -c 131072 = 65536/slot) ====='
Stop-Server
Start-GuardedServer -FilePath $exe -ArgumentList @('-m', $iq4, '--alias', 'q', '-c', '131072', '-ngl', '99',
    '--parallel', '2', '--load-mode', 'none', '-ctk', 'q8_0', '-ctv', 'q8_0',
    '--spec-type', 'draft-mtp', '--spec-draft-n-max', '4', '--spec-draft-p-min', '0.75',
    '--jinja', '--host', '127.0.0.1', '--port', '1234') -WindowStyle Hidden
if (-not (Wait-Health)) { Write-Output 'P3 SERVER FAILED' } else {
  $body = @{ model='q'; temperature=0; top_k=1; max_tokens=500
             messages=@(@{role='user';content=$code}) } | ConvertTo-Json -Depth 5
  $bytes = [Text.Encoding]::UTF8.GetBytes($body)
  $sw = [Diagnostics.Stopwatch]::StartNew()
  $r0 = Invoke-RestMethod -Uri 'http://127.0.0.1:1234/v1/chat/completions' -Method Post -ContentType 'application/json' -Body $bytes -TimeoutSec 0
  $sw.Stop()
  Write-Output ('serial reference: ' + [math]::Round($r0.usage.completion_tokens / $sw.Elapsed.TotalSeconds, 1) + ' t/s (' + [math]::Round($sw.Elapsed.TotalSeconds,1) + ' s)')
  $job = { param($b) $s=[Diagnostics.Stopwatch]::StartNew(); $r=Invoke-RestMethod -Uri 'http://127.0.0.1:1234/v1/chat/completions' -Method Post -ContentType 'application/json' -Body $b -TimeoutSec 0; $s.Stop(); @($r.usage.completion_tokens, [math]::Round($s.Elapsed.TotalSeconds,1)) }
  $sw2 = [Diagnostics.Stopwatch]::StartNew()
  $j1 = Start-Job -ScriptBlock $job -ArgumentList (,$bytes)
  $j2 = Start-Job -ScriptBlock $job -ArgumentList (,$bytes)
  $a = Receive-Job -Job $j1 -Wait; $b2 = Receive-Job -Job $j2 -Wait
  $sw2.Stop()
  Remove-Job $j1, $j2 -Force -ErrorAction SilentlyContinue
  Write-Output ('concurrent pair: req1 ' + $a[0] + ' tok/' + $a[1] + ' s, req2 ' + $b2[0] + ' tok/' + $b2[1] + ' s, both done in ' + [math]::Round($sw2.Elapsed.TotalSeconds,1) + ' s')
  Write-Output ('aggregate: ' + [math]::Round((([double]$a[0] + [double]$b2[0]) / $sw2.Elapsed.TotalSeconds), 1) + ' t/s combined')
}

Write-Output '===== PART 4: multi-image (hi-res vision, 3 different pages) ====='
Stop-Server
Start-GuardedServer -FilePath $exe -ArgumentList @('-m', $iq4, '--mmproj', $mmproj, '--image-min-tokens', '1024', '--image-max-tokens', '10580',
    '--alias', 'q', '-c', '122880', '-ngl', '99', '--parallel', '1', '--load-mode', 'none',
    '-ctk', 'q8_0', '-ctv', 'q8_0', '--spec-type', 'draft-mtp', '--spec-draft-n-max', '4', '--spec-draft-p-min', '0.75',
    '--jinja', '--host', '127.0.0.1', '--port', '1234') -WindowStyle Hidden
if (-not (Wait-Health)) { Write-Output 'P4 SERVER FAILED' } else {
  function B64([string]$p) { return 'data:image/png;base64,' + [Convert]::ToBase64String([IO.File]::ReadAllBytes($p)) }
  $content = @(
    @{ type='text'; text='Three screenshots of three DIFFERENT aquarium implementations, in order: image 1, image 2, image 3. Rank them by visual richness (most creatures and detail first), and say which one, if any, looks broken or nearly empty. One short paragraph.' },
    @{ type='image_url'; image_url=@{ url=(B64 'E:\AI\aider\qwen\aquarium-4k.png') } },
    @{ type='image_url'; image_url=@{ url=(B64 'E:\AI\aider\qwen\aquarium-1440p.png') } },
    @{ type='image_url'; image_url=@{ url=(B64 'E:\AI\aider\qwen\aquarium-1080p.png') } }
  )
  $payload = @{ model='q'; max_tokens=2500; messages=@(@{ role='user'; content=$content }) } | ConvertTo-Json -Depth 8
  $sw3 = [Diagnostics.Stopwatch]::StartNew()
  $r = Invoke-RestMethod -Uri 'http://127.0.0.1:1234/v1/chat/completions' -Method Post -ContentType 'application/json' -Body ([Text.Encoding]::UTF8.GetBytes($payload)) -TimeoutSec 0
  $sw3.Stop()
  Write-Output ('3 images: prompt_tokens=' + $r.usage.prompt_tokens + ', wall ' + [math]::Round($sw3.Elapsed.TotalSeconds,1) + ' s')
  Write-Output '--- reply ---'
  Write-Output $r.choices[0].message.content
}
Stop-Server
Write-Output 'NUANCE SUITE DONE'
