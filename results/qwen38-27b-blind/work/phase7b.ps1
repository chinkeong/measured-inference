# Phase 7b - METHODOLOGY rule 7: an arm that truncated gets its cap raised and
# re-run, and ONLY that arm. xhigh hit the 65,536-token cap exactly
# (finish_reason=length) with ~161k characters of thinking and an unfinished
# answer. Re-run it at 120,000, which is the largest cap that still fits inside
# -c 131072 alongside the 1,701-token prompt.
#
# This is deliberately the LAST GPU job of the campaign: if it does not finish
# inside the time budget, everything else is already measured and the report
# ships the truncation as the finding.
$ErrorActionPreference = 'Continue'
. 'E:\AI\measured-inference\results\qwen38-27b-blind\work\lib.ps1'
$out = Join-Path $script:DATA 'phase7b.txt'
if (-not (Test-Path $out)) { New-Item -ItemType File -Path $out | Out-Null }
$done = Get-Content $out -ErrorAction SilentlyContinue
if ($done -match '^RESULT effort-xhigh-120k ') { Write-Host 'already done'; exit 0 }

$prompt = [IO.File]::ReadAllText('E:\AI\measured-inference\templates\effort-task-example.md')
$pw = Join-Path $script:DATA 'power-xhigh120k.csv'
$logger = Start-Process -FilePath 'nvidia-smi' -ArgumentList @('--query-gpu=timestamp,power.draw','--format=csv,noheader','-l','1') `
    -WindowStyle Hidden -RedirectStandardOutput $pw -RedirectStandardError (Join-Path $script:DATA 'power-x.err') -PassThru

$s = Start-Srv -Extra @('-c','131072','-ngl','99','--parallel','1','--load-mode','mmap','-ctk','q8_0','-ctv','q8_0',
    '--reasoning-preserve','--chat-template-kwargs','{\"reasoning_effort\":\"xhigh\"}',
    '--spec-type','draft-mtp','--spec-draft-n-max','4','--spec-draft-p-min','0.75') -Tag 'effort-xhigh-120k' -TimeoutSec 600
if (-not $s) { Write-Row $out 'RESULT effort-xhigh-120k LOAD-FAILED'; try { $logger | Stop-Process -Force } catch {}; exit 1 }
Start-Sleep -Seconds 5
$t0 = (Get-Date).ToString('yyyy/MM/dd HH:mm:ss')
$r = Invoke-Probe -Text $prompt -MaxTokens 120000 -Temp 1.0 -TopK 20 -TopP 0.95
$t1 = (Get-Date).ToString('yyyy/MM/dd HH:mm:ss')
$body = ''
if ($r.think) { $body += "===== THINKING =====`r`n" + $r.think + "`r`n`r`n===== ANSWER =====`r`n" }
$body += $r.text
[IO.File]::WriteAllText((Join-Path $script:DATA 'effort-xhigh-120k.txt'), $body, [Text.UTF8Encoding]::new($false))
$html = $r.text
$m = [regex]::Match($html, '(?s)<!DOCTYPE html.*?</html>')
if ($m.Success) { $html = $m.Value }
[IO.File]::WriteAllText((Join-Path $script:DATA 'effort-xhigh-120k.html'), $html, [Text.UTF8Encoding]::new($false))
$acc = 'n/a'
if ($r.draft_n -and [double]$r.draft_n -gt 0) { $acc = [math]::Round([double]$r.draft_acc / [double]$r.draft_n, 4) }
Write-Row $out ("RESULT effort-xhigh-120k prompt_n={0} predicted_n={1} decode_tps={2} wall_s={3} finish={4} accept={5} think_chars={6} answer_chars={7} html_ok={8} t0=[{9}] t1=[{10}]" -f `
    $r.prompt_n, $r.predicted_n, $r.decode_tps, $r.wall_s, $r.finish, $acc, $r.think.Length, $r.text.Length, $m.Success, $t0, $t1)
Stop-Srv
Start-Sleep -Seconds 3
try { $logger | Stop-Process -Force -Confirm:$false } catch {}
Write-Host 'PHASE7B DONE'
