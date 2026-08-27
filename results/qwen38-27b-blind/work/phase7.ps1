# Phase 7 (reduced) - effort cost + Phase 10 power, in one pass.
# ONE run per effort level (low/medium/xhigh) of the aquarium task at the
# model card's sampling (temp 1.0 / top_p 0.95 / top_k 20). n=1: cost numbers
# are single samples, NOT a ranking.
# A nvidia-smi power logger runs for the whole phase; per-run start/end
# timestamps are recorded so each level's kWh can be integrated afterwards.
$ErrorActionPreference = 'Continue'
. 'E:\AI\measured-inference\results\qwen38-27b-blind\work\lib.ps1'
$out = Join-Path $script:DATA 'phase7.txt'
if (-not (Test-Path $out)) { New-Item -ItemType File -Path $out | Out-Null }
$done = Get-Content $out -ErrorAction SilentlyContinue

$SPEC = @('--spec-type','draft-mtp','--spec-draft-n-max','4','--spec-draft-p-min','0.75')
if ($env:PH7_SPEC) { $SPEC = $env:PH7_SPEC -split ' ' }
$CTX = 131072
if ($env:PH7_CTX) { $CTX = [int]$env:PH7_CTX }
$prompt = [IO.File]::ReadAllText('E:\AI\measured-inference\templates\effort-task-example.md')

# --- power logger for the whole phase (Phase 10) ---
$pw = Join-Path $script:DATA 'power.csv'
$pwErr = Join-Path $script:DATA 'power.err'
$logger = Start-Process -FilePath 'nvidia-smi' -ArgumentList @('--query-gpu=timestamp,power.draw,utilization.gpu,memory.used','--format=csv,noheader','-l','1') `
    -WindowStyle Hidden -RedirectStandardOutput $pw -RedirectStandardError $pwErr -PassThru
Start-Sleep -Seconds 12   # idle baseline window before any server is up

foreach ($e in @('low','medium','xhigh')) {
    if ($done -match ("^RESULT effort-$e ")) { Write-Host "skip $e"; continue }
    Write-Host "=== effort $e ==="
    $kw = '{\"reasoning_effort\":\"' + $e + '\"}'
    $extra = @('-c', "$CTX", '-ngl','99','--parallel','1','--load-mode','mmap','-ctk','q8_0','-ctv','q8_0',
               '--reasoning-preserve','--chat-template-kwargs', $kw) + $SPEC
    $s = Start-Srv -Extra $extra -Tag "effort-$e" -TimeoutSec 600
    if (-not $s) { Write-Row $out ("RESULT effort-{0} LOAD-FAILED" -f $e); continue }
    Start-Sleep -Seconds 5
    $t0 = (Get-Date).ToString('yyyy/MM/dd HH:mm:ss')
    $r = Invoke-Probe -Text $prompt -MaxTokens 65536 -Temp 1.0 -TopK 20 -TopP 0.95
    $t1 = (Get-Date).ToString('yyyy/MM/dd HH:mm:ss')
    $body = ''
    if ($r.think) { $body += "===== THINKING =====`r`n" + $r.think + "`r`n`r`n===== ANSWER =====`r`n" }
    $body += $r.text
    [IO.File]::WriteAllText((Join-Path $script:DATA "effort-$e.txt"), $body, [Text.UTF8Encoding]::new($false))
    # extract the HTML answer
    $html = $r.text
    $m = [regex]::Match($html, '(?s)<!DOCTYPE html.*?</html>')
    if ($m.Success) { $html = $m.Value }
    [IO.File]::WriteAllText((Join-Path $script:DATA "effort-$e.html"), $html, [Text.UTF8Encoding]::new($false))
    $acc = 'n/a'
    if ($r.draft_n -and [double]$r.draft_n -gt 0) { $acc = [math]::Round([double]$r.draft_acc / [double]$r.draft_n, 4) }
    $thinkTok = 0
    Write-Row $out ("RESULT effort-{0} prompt_n={1} predicted_n={2} decode_tps={3} wall_s={4} finish={5} accept={6} think_chars={7} answer_chars={8} html_ok={9} t0=[{10}] t1=[{11}]" -f `
        $e, $r.prompt_n, $r.predicted_n, $r.decode_tps, $r.wall_s, $r.finish, $acc, $r.think.Length, $r.text.Length, $m.Success, $t0, $t1)
    Stop-Srv
    Start-Sleep -Seconds 8
}
Start-Sleep -Seconds 5
try { $logger | Stop-Process -Force -Confirm:$false } catch {}
Write-Host 'PHASE7 DONE'
