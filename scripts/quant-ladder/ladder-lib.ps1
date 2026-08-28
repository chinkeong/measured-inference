# ladder-lib.ps1 - shared helpers for the quant-ladder campaign (run-ladder.ps1,
# detectors.ps1). Windows PowerShell 5.1.
#
# PS 5.1 rules obeyed here (reference/platform-notes.md):
#   - Write-Host, never Write-Output, for logging INSIDE a function: Write-Output
#     pollutes the function's return value.
#   - Native stderr is captured via Start-Process redirection, never `2>&1` in
#     the pipeline (that wraps every line in a NativeCommandError record and
#     flips $? to false on a successful exit).
#   - No variable named $base.
#   - Callers parse-check with [scriptblock]::Create before detaching.

. (Join-Path $PSScriptRoot "..\gpu-lock.ps1")
$ErrorActionPreference = 'Continue'

function Write-Log {
    param([string]$Msg)
    Write-Host ('[{0}] {1}' -f (Get-Date -Format 'MM-dd HH:mm:ss'), $Msg)
}

function Write-Ledger {
    # A dropped ledger line is silent data loss - the measurement happened and
    # the report would never know. So: retry, and if the file is still locked
    # after 30 s, spill the line to a side file rather than lose it. (Earned
    # 2026-08-23: a `tail -f` from Git Bash opens Windows files WITHOUT
    # FILE_SHARE_WRITE and blocked Add-Content for two lines. Never tail -f a
    # file a PowerShell run is appending to - snapshot it with Get-Content,
    # which opens FileShare.ReadWrite.)
    param([string]$Path, [string]$Line)
    $done = $false
    for ($i = 0; $i -lt 15; $i++) {
        try {
            Add-Content -Path $Path -Value $Line -Encoding utf8 -ErrorAction Stop
            $done = $true
            break
        } catch {
            Start-Sleep -Seconds 2
        }
    }
    if (-not $done) {
        $spill = $Path + '.spill'
        try { Add-Content -Path $spill -Value $Line -Encoding utf8 -ErrorAction Stop } catch {}
        Write-Host ('  LEDGER LOCKED - line spilled to {0}' -f $spill)
    }
    Write-Host $Line
}

function Get-Manifest {
    param([string]$Path)
    $txt = Get-Content -Raw -LiteralPath $Path
    return ($txt | ConvertFrom-Json)
}

function Test-LedgerHas {
    param([string]$Path, [string]$Prefix)
    if (-not (Test-Path -LiteralPath $Path)) { return $false }
    $hit = Select-String -Path $Path -SimpleMatch -Pattern $Prefix -ErrorAction SilentlyContinue
    if ($hit) { return $true }
    return $false
}

function Get-LedgerField {
    # Pull one "key=value" field out of the RESULT line for a named rung.
    param([string]$Path, [string]$Name, [string]$Key)
    if (-not (Test-Path -LiteralPath $Path)) { return $null }
    # [﻿]? - PS 5.1 writes a BOM on the first line of a utf8 file
    $line = Select-String -Path $Path -Pattern ('^[﻿]?RESULT\s+' + [regex]::Escape($Name) + '\s') |
        Select-Object -Last 1
    if (-not $line) { return $null }
    $m = [regex]::Match($line.Line, [regex]::Escape($Key) + '=([^\s|]+)')
    if ($m.Success) { return $m.Groups[1].Value }
    return $null
}

# ---------------------------------------------------------------- GPU GATE ---

function Get-VramUsedMiB {
    $v = -1
    try {
        $raw = (nvidia-smi --query-gpu=memory.used --format=csv,noheader,nounits) | Select-Object -First 1
        $v = [int]("$raw".Trim())
    } catch { $v = -1 }
    return $v
}

function Test-GpuFree {
    # THREE conditions, all required (the coordination contract):
    #   1. the other session's runner PID is dead (identity confirmed by start
    #      time, so a recycled PID cannot block us forever),
    #   2. no llama-* process of any kind exists,
    #   3. nvidia-smi memory.used < max_vram_mib.
    param($Gate, [switch]$Quiet)
    $p = $null
    try { $p = Get-Process -Id ([int]$Gate.holder_pid) -ErrorAction SilentlyContinue } catch { $p = $null }
    if ($p) {
        $same = $true
        try {
            if ($Gate.holder_start_iso) {
                $same = ($p.StartTime.ToString('o') -eq [string]$Gate.holder_start_iso)
            }
        } catch { $same = $true }
        if ($same) {
            if (-not $Quiet) { Write-Host ('  gate: CLOSED - holder PID {0} still alive' -f $Gate.holder_pid) }
            return $false
        }
    }
    $l = Get-Process -Name ([string[]]$Gate.llama_procs) -ErrorAction SilentlyContinue
    if ($l) {
        if (-not $Quiet) {
            $who = (($l | ForEach-Object { $_.ProcessName + '/' + $_.Id }) -join ', ')
            Write-Host ('  gate: CLOSED - llama process alive: {0}' -f $who)
        }
        return $false
    }
    $used = Get-VramUsedMiB
    if ($used -lt 0) {
        if (-not $Quiet) { Write-Host '  gate: CLOSED - nvidia-smi unreadable' }
        return $false
    }
    if ($used -ge [int]$Gate.max_vram_mib) {
        if (-not $Quiet) { Write-Host ('  gate: CLOSED - VRAM {0} MiB >= {1} MiB' -f $used, $Gate.max_vram_mib) }
        return $false
    }
    if (-not $Quiet) { Write-Host ('  gate: OPEN - VRAM {0} MiB' -f $used) }
    return $true
}

function Wait-GpuGate {
    # Blocks until the gate opens or the deadline passes. Returns $true if open.
    param($Gate, [datetime]$Deadline)
    $n = 0
    while ($true) {
        if (Test-GpuFree -Gate $Gate -Quiet:($n -gt 0 -and ($n % 10) -ne 0)) { return $true }
        if ((Get-Date) -ge $Deadline) { Write-Log 'GPU gate never opened before the deadline'; return $false }
        $n++
        if ($n -eq 1) { Write-Log ('waiting on the GPU gate (poll {0}s)...' -f $Gate.poll_s) }
        Start-Sleep -Seconds ([int]$Gate.poll_s)
    }
}

# --------------------------------------------------------------- FILE GATE ---

function Test-FileStable {
    # Returns the byte size when the file exists AND its size is unchanged
    # across a recheck window; $null otherwise. A mid-download file must never
    # be measured, and this runner never creates, moves or deletes any weight.
    param([string]$Path, [int]$RecheckSec = 60)
    if (-not (Test-Path -LiteralPath $Path)) { return $null }
    $s1 = (Get-Item -LiteralPath $Path).Length
    if ($s1 -le 0) { return $null }
    Write-Host ('  file: present {0:N0} bytes ({1:N3} GiB) - rechecking in {2}s' -f $s1, ($s1 / 1GB), $RecheckSec)
    Start-Sleep -Seconds $RecheckSec
    if (-not (Test-Path -LiteralPath $Path)) { Write-Host '  file: vanished during the recheck'; return $null }
    $s2 = (Get-Item -LiteralPath $Path).Length
    if ($s2 -ne $s1) {
        Write-Host ('  file: STILL GROWING {0:N0} -> {1:N0} bytes - not ready' -f $s1, $s2)
        return $null
    }
    Write-Host ('  file: STABLE at {0:N0} bytes ({1:N3} GiB)' -f $s2, ($s2 / 1GB))
    return $s2
}

# ------------------------------------------------------------------ SERVER ---

function Stop-Srv {
    try { Get-Process llama-server -ErrorAction Stop | Stop-Process -Force -Confirm:$false } catch {}
    Start-Sleep -Seconds 3
}

function Start-Srv {
    param([string]$ModelPath, [string]$Tag, [string[]]$Flags, [int]$Port,
          [string]$LogDir, [int]$TimeoutSec = 900)
    Stop-Srv
    $errLog = Join-Path $LogDir ('srv-{0}.err.log' -f $Tag)
    $outLog = Join-Path $LogDir ('srv-{0}.out.log' -f $Tag)
    Remove-Item $errLog, $outLog -ErrorAction SilentlyContinue
    $a = @('-m', $ModelPath, '--alias', 'ladder', '--host', '127.0.0.1', '--port', "$Port") + $Flags
    $sw = [Diagnostics.Stopwatch]::StartNew()
    $proc = Start-GuardedServer -FilePath 'E:\AI\llama.cpp\llama-server.exe' -ArgumentList $a `
        -WindowStyle Hidden -RedirectStandardError $errLog -RedirectStandardOutput $outLog -PassThru
    $ok = $false
    $url = "http://127.0.0.1:$Port"
    for ($i = 0; $i -lt ($TimeoutSec / 2); $i++) {
        Start-Sleep -Seconds 2
        try {
            $h = Invoke-RestMethod "$url/health" -TimeoutSec 3
            if ($h.status -eq 'ok') { $ok = $true; break }
        } catch {}
        if ($proc.HasExited) { break }
    }
    $sw.Stop()
    if (-not $ok) {
        Write-Host ('  [{0}] SERVER FAILED (exited={1}) after {2}s' -f $Tag, $proc.HasExited, [math]::Round($sw.Elapsed.TotalSeconds, 1))
        if (Test-Path $errLog) { Get-Content $errLog -Tail 15 | ForEach-Object { Write-Host ('    | ' + $_) } }
        Stop-Srv
        return $null
    }
    Write-Host ('  [{0}] server healthy in {1}s' -f $Tag, [math]::Round($sw.Elapsed.TotalSeconds, 1))
    return [pscustomobject]@{ proc = $proc; err = $errLog; out = $outLog; load_s = [math]::Round($sw.Elapsed.TotalSeconds, 1) }
}

function Invoke-Probe {
    # Greedy by construction: temperature 0, top_k 1. Returns the server's own
    # timings, plus reasoning_content when the model emits any.
    param([string]$Text, [int]$MaxTokens = 700, [int]$Port = 1235, [int]$TimeoutSec = 900)
    $msgs = @(@{ role = 'user'; content = $Text })
    $b = @{ model = 'ladder'; temperature = 0; top_k = 1; max_tokens = $MaxTokens; messages = $msgs }
    $body = $b | ConvertTo-Json -Depth 12 -Compress
    $url = "http://127.0.0.1:$Port/v1/chat/completions"
    $sw = [Diagnostics.Stopwatch]::StartNew()
    $resp = $null
    $err = $null
    try {
        $resp = Invoke-RestMethod -Uri $url -Method Post -ContentType 'application/json' `
            -Body ([Text.Encoding]::UTF8.GetBytes($body)) -TimeoutSec $TimeoutSec
    } catch { $err = "$_" }
    $sw.Stop()
    if (-not $resp) {
        Write-Host ('  probe FAILED: {0}' -f $err)
        return [pscustomobject]@{ ok = $false; error = $err; wall_s = [math]::Round($sw.Elapsed.TotalSeconds, 2) }
    }
    $t = $resp.timings
    $msg = $resp.choices[0].message
    $think = ''
    if ($msg.PSObject.Properties.Name -contains 'reasoning_content') { $think = [string]$msg.reasoning_content }
    return [pscustomobject]@{
        ok           = $true
        wall_s       = [math]::Round($sw.Elapsed.TotalSeconds, 2)
        prompt_n     = $(if ($t) { $t.prompt_n } else { $null })
        predicted_n  = $(if ($t) { $t.predicted_n } else { $null })
        decode_tps   = $(if ($t) { [math]::Round($t.predicted_per_second, 2) } else { $null })
        finish       = $resp.choices[0].finish_reason
        text         = [string]$msg.content
        think        = $think
    }
}
