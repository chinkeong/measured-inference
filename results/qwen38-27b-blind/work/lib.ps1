# Shared harness for the qwen38-27b-blind campaign.
# Adapted from scripts/reference-3090/probe-config.ps1 + iq4-ctx-sweep.ps1.
# PS 5.1 rules: Write-Host for logs inside functions (Write-Output pollutes
# return values); every function returns exactly one object or nothing.

$script:EXE    = 'E:\AI\llama.cpp\llama-server.exe'
$script:MODEL  = 'C:\Users\chink\.lmstudio\models\unsloth\Qwen3.8-27B-GGUF\Qwen3.8-27B-UD-IQ4_XS.gguf'
$script:MMPROJ = 'C:\Users\chink\.lmstudio\models\lmstudio-community\Qwen3.8-27B-GGUF\mmproj-Qwen3.8-27B-BF16.gguf'
$script:ALIAS  = 'qwen/qwen3.8-27b'
$script:DATA   = 'E:\AI\measured-inference\results\qwen38-27b-blind\data'
# DEVIATION: port 1234 is held by a running LM Studio instance on this machine;
# the campaign measures on 1235. Port has no effect on any measured quantity.
$script:PORT   = 1235
$script:BASE   = "http://127.0.0.1:$($script:PORT)"

function Stop-Srv {
    try { Get-Process llama-server -ErrorAction Stop | Stop-Process -Force -Confirm:$false } catch {}
    Start-Sleep -Seconds 3
}

function Get-Vram {
    # Total board usage (includes desktop overhead). Windows nvidia-smi is
    # per-process blind, so llama-server's own dedicated/shared split comes
    # from the GPU Process Memory perf counters.
    $tot = 0
    try { $tot = [int](((nvidia-smi --query-gpu=memory.used --format=csv,noheader,nounits) | Select-Object -First 1).Trim()) } catch {}
    $ded = 0; $shr = 0
    $p = Get-Process llama-server -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($p) {
        try {
            $c = Get-Counter '\GPU Process Memory(*)\Dedicated Usage' -ErrorAction Stop
            foreach ($s in $c.CounterSamples) { if ($s.InstanceName -match "pid_$($p.Id)_") { $ded += $s.CookedValue } }
            $c2 = Get-Counter '\GPU Process Memory(*)\Shared Usage' -ErrorAction Stop
            foreach ($s in $c2.CounterSamples) { if ($s.InstanceName -match "pid_$($p.Id)_") { $shr += $s.CookedValue } }
        } catch {}
    }
    return [pscustomobject]@{
        board_mib = $tot
        srv_ded_mib = [math]::Round($ded / 1MB, 0)
        srv_shr_mib = [math]::Round($shr / 1MB, 0)
    }
}

function Start-Srv {
    param([string[]]$Extra, [string]$Tag = 'srv', [int]$TimeoutSec = 900)
    Stop-Srv
    $errLog = Join-Path $script:DATA "srv-$Tag.err.log"
    $outLog = Join-Path $script:DATA "srv-$Tag.out.log"
    Remove-Item $errLog, $outLog -ErrorAction SilentlyContinue
    $a = @('-m', $script:MODEL, '--alias', $script:ALIAS,
           '--host', '127.0.0.1', '--port', "$($script:PORT)", '--jinja') + $Extra
    $sw = [Diagnostics.Stopwatch]::StartNew()
    $proc = Start-Process -FilePath $script:EXE -ArgumentList $a -WindowStyle Hidden `
        -RedirectStandardError $errLog -RedirectStandardOutput $outLog -PassThru
    $ok = $false
    for ($i = 0; $i -lt ($TimeoutSec / 2); $i++) {
        Start-Sleep -Seconds 2
        try { $h = Invoke-RestMethod "$($script:BASE)/health" -TimeoutSec 3; if ($h.status -eq 'ok') { $ok = $true; break } } catch {}
        if ($proc.HasExited) { break }
    }
    $sw.Stop()
    if (-not $ok) {
        Write-Host "  [$Tag] SERVER FAILED (exited=$($proc.HasExited)) after $([math]::Round($sw.Elapsed.TotalSeconds,1))s"
        if (Test-Path $errLog) { Get-Content $errLog -Tail 12 | ForEach-Object { Write-Host "    | $_" } }
        Stop-Srv
        return $null
    }
    Write-Host "  [$Tag] healthy in $([math]::Round($sw.Elapsed.TotalSeconds,1))s"
    return [pscustomobject]@{ proc = $proc; err = $errLog; out = $outLog; load_s = [math]::Round($sw.Elapsed.TotalSeconds,1) }
}

function Invoke-Probe {
    # Returns the server's own timings, never wall-clock-including-prefill.
    param([string]$Text, [int]$MaxTokens = 700, [double]$Temp = 0, [int]$TopK = 1,
          [string]$System = $null, [object[]]$ExtraContent = $null, [double]$TopP = 1.0)
    $content = $Text
    if ($ExtraContent) { $content = @(@{ type = 'text'; text = $Text }) + $ExtraContent }
    $msgs = @()
    if ($System) { $msgs += @{ role = 'system'; content = $System } }
    $msgs += @{ role = 'user'; content = $content }
    $b = @{ model = $script:ALIAS; temperature = $Temp; max_tokens = $MaxTokens; messages = $msgs }
    if ($TopK -gt 0) { $b['top_k'] = $TopK }
    if ($TopP -lt 1.0) { $b['top_p'] = $TopP }
    $body = $b | ConvertTo-Json -Depth 12 -Compress
    $sw = [Diagnostics.Stopwatch]::StartNew()
    $resp = Invoke-RestMethod -Uri "$($script:BASE)/v1/chat/completions" -Method Post `
        -ContentType 'application/json' -Body ([Text.Encoding]::UTF8.GetBytes($body)) -TimeoutSec 0
    $sw.Stop()
    $t = $resp.timings
    $msg = $resp.choices[0].message
    $txt = $msg.content
    $think = ''
    if ($msg.PSObject.Properties.Name -contains 'reasoning_content') { $think = [string]$msg.reasoning_content }
    return [pscustomobject]@{
        wall_s        = [math]::Round($sw.Elapsed.TotalSeconds, 2)
        prompt_tokens = $resp.usage.prompt_tokens
        compl_tokens  = $resp.usage.completion_tokens
        prompt_n      = $(if ($t) { $t.prompt_n } else { $null })
        prompt_ms     = $(if ($t) { [math]::Round($t.prompt_ms, 1) } else { $null })
        prefill_tps   = $(if ($t) { [math]::Round($t.prompt_per_second, 1) } else { $null })
        predicted_n   = $(if ($t) { $t.predicted_n } else { $null })
        predicted_ms  = $(if ($t) { [math]::Round($t.predicted_ms, 1) } else { $null })
        decode_tps    = $(if ($t) { [math]::Round($t.predicted_per_second, 2) } else { [math]::Round($resp.usage.completion_tokens / $sw.Elapsed.TotalSeconds, 2) })
        draft_n       = $(if ($t -and ($t.PSObject.Properties.Name -contains 'draft_n')) { $t.draft_n } else { $null })
        draft_acc     = $(if ($t -and ($t.PSObject.Properties.Name -contains 'draft_n_accepted')) { $t.draft_n_accepted } else { $null })
        finish        = $resp.choices[0].finish_reason
        text          = $txt
        think         = $think
    }
}

function Write-Row { param([string]$Path, [string]$Line)
    Add-Content -Path $Path -Value $Line -Encoding utf8
    Write-Host $Line
}

# Canonical probes
$script:CODE_PROBE = 'Write a single self-contained JavaScript file implementing a red-black tree class with insert, delete, search and an in-order iterator. Code only, no explanation.'
