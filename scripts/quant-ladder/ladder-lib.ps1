# ladder-lib.ps1 - shared helpers for the quant-ladder campaign (run-ladder.ps1,
# detectors.ps1). Windows PowerShell 5.1.
#
# Nothing in this file names a machine. Every path it needs is resolved when it
# is used - see the SERVER section for the chain and for the one-line answer to
# "which llama.cpp did this campaign actually measure with".
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
    # The manifest, with its two llama.cpp tool paths resolved on the way out.
    #
    # `ppl.exe` and `tokenize.exe` are HINTS, not addresses - the contract
    # run-ladder.py's resolve_bin() has always applied to them and the reason
    # its header can say the same manifest runs unedited on two machines.
    # run-ladder.ps1 hands both values straight to Start-Process and has no
    # resolver of its own, so the resolution happens here, in the one function
    # every ladder script already calls, and it happens at LOAD time: a missing
    # toolchain is then named before the GPU gate is waited on rather than
    # after (rule 2).
    #
    # NON-FATAL by design. detectors.ps1 needs neither tool, so a machine that
    # cannot resolve llama-perplexity must still be able to run the
    # disqualifier probes. When the chain comes up empty the manifest's own
    # value is left exactly as it was, the resolver's message is logged in
    # full - it carries the fix - and the launch fails where it always failed.
    param([string]$Path)
    $txt = Get-Content -Raw -LiteralPath $Path
    $m = ($txt | ConvertFrom-Json)
    foreach ($pair in @(@{ key = 'ppl'; tool = 'llama-perplexity' },
                        @{ key = 'tokenize'; tool = 'llama-tokenize' })) {
        $node = $m.($pair.key)
        if (-not $node) { continue }
        $hint = ''
        if ($node.PSObject.Properties['exe']) { $hint = [string]$node.exe }
        $bin = $null
        try {
            $bin = Get-LlamaToolBin -Tool $pair.tool -Explicit $hint
        } catch {
            Write-Log ('{0}: NOT RESOLVED on this machine. The manifest value stands unchanged ({1}) and any runner that launches it fails there:' -f $pair.tool, $hint)
            foreach ($ln in ("$_" -split "`r?`n")) { Write-Log ('    ' + $ln) }
            continue
        }
        if ($node.PSObject.Properties['exe']) { $node.exe = $bin }
        else { Add-Member -InputObject $node -NotePropertyName 'exe' -NotePropertyValue $bin -Force }
    }
    return $m
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

# ------------------------------------------------------- TOOLCHAIN + SERVER ---

# WHERE THE llama.cpp TOOLS ARE, and why none of them is written down here.
# Until 2026-08-30 this section said
#     Start-GuardedServer -FilePath 'E:\AI\llama.cpp\llama-server.exe'
# which is one machine's answer typed into a shared library: on every other
# clone the disqualifier probes died at the first launch, and they died AFTER
# the GPU gate had been waited on, which is the expensive kind of failure
# scripts/verify/portability-audit.py exists to count.
#
# `scripts/lib/paths.py` llama_bin() is this repository's canonical resolver and
# its header explains why a "default that usually works" is the thing the repo
# refuses to ship. PowerShell cannot import a Python module, so the chain below
# is a SECOND, SHORTER copy of it: the same order, minus paths.py's
# campaign.json "llama_dir" step, which needs the slug disambiguation that
# module owns and that a second copy would get subtly wrong. The consequence is
# recorded here rather than discovered later: a campaign that pins "llama_dir"
# in campaign.json and exports nothing can resolve one build for run-ladder.py
# and another for these probes. That is why the resolved path and the step that
# produced it are logged once per tool per run - the binary is a condition, and
# a condition travels with the numbers it produced (rule 3).
#
# The chain serves all three tools this campaign launches. llama-server is the
# one these probes start; the manifest's `ppl.exe` and `tokenize.exe` go
# through the same chain as hints when Get-Manifest loads the file, because
# run-ladder.ps1 launches those two values literally and has no resolver of its
# own - so the perplexity and tokenize halves of the ladder are resolved at the
# point of use as well, and not only the disqualifier probes.

$script:LlamaToolBin = @{}

function Get-LlamaToolCandidates {
    # The four files a llama.cpp directory can hold for one tool, in paths.py
    # _in_dir() order: the release layout <dir>\<tool> and the cmake layout
    # <dir>\build\bin\<tool>, each with and without .exe.
    #
    # The cmake layout is there for a $env:LLAMA_DIR pointed at a llama.cpp
    # SOURCE tree, which is where `cmake --build` leaves the binaries. Neither
    # installer writes one into <repo>\bin\llama.cpp: scripts\setup.ps1 is a
    # download - "not a source build", in its own .DESCRIPTION - and expands
    # the release zip flat into that directory; scripts\setup.sh builds in a
    # separate source clone and copies build/bin/<tool> out into the same flat
    # directory, so a POSIX clone whose copy step died leaves the tools in that
    # clone's build/bin and nowhere else, which is otherwise mystifying to
    # debug.
    param([string]$Directory, [string]$Tool)
    $out = @()
    foreach ($d in @($Directory, (Join-Path $Directory 'build\bin'))) {
        $out += (Join-Path $d $Tool)
        $out += (Join-Path $d ($Tool + '.exe'))
    }
    return $out
}

function Get-BinaryMismatch {
    # Why this file cannot be launched on this host, or $null when it can.
    #
    # Existing is not the same as runnable, and the mismatch is live in THIS
    # clone right now: bin\llama.cpp\llama-server is a Linux ELF built under WSL
    # (bin\llama.cpp\INSTALL.json says "os":"linux"), so a resolver that stopped
    # at "the file is there" would hand Start-Process a binary Windows answers
    # with "not a valid Win32 application" - after Stop-Srv has killed whatever
    # was serving. Magic bytes only, matching paths.py _unusable(); the POSIX
    # executable-bit case stays that module's, because PS 5.1 cannot read a Unix
    # mode, and a file that is merely un-chmod'd fails loudly at launch anyway.
    param([string]$Path)
    $magic = $null
    try {
        $fs = [IO.File]::OpenRead($Path)
        try {
            $buf = New-Object byte[] 4
            if ($fs.Read($buf, 0, 4) -ge 4) { $magic = $buf }
        } finally { $fs.Dispose() }
    } catch { return ('unreadable: ' + $_.Exception.Message) }
    if (-not $magic) { return 'shorter than 4 bytes - not a binary' }
    $isElf = ($magic[0] -eq 0x7F -and $magic[1] -eq 0x45 -and $magic[2] -eq 0x4C -and $magic[3] -eq 0x46)
    $isPe = ($magic[0] -eq 0x4D -and $magic[1] -eq 0x5A)
    # $IsWindows does not exist in PS 5.1; $env:OS does, and is 'Windows_NT'
    # there and unset under pwsh on Linux.
    if ($env:OS -eq 'Windows_NT') {
        if ($isElf) { return 'a Linux ELF binary, which cannot run on Windows' }
        return $null
    }
    if ($isPe) { return 'a Windows PE binary, which cannot run on this OS' }
    return $null
}

function Get-LlamaToolBin {
    <#
      A llama.cpp tool - llama-server for the disqualifier probes,
      llama-perplexity and llama-tokenize for the ladder itself - resolved at
      the point of use. Order:

        1. -Explicit              a caller that already knows (a flag, a
                                  manifest key), offered as a hint only
        2. $env:LLAMA_SERVER      the binary itself; llama-server only, as in
                                  paths.py, because that variable names a file
                                  and not a directory
        3. $env:LLAMA_DIR         a directory holding the llama.cpp tools
        4. PATH
        5. <repo>\bin\llama.cpp\  what scripts\setup.ps1 bootstraps into

      and then a throw carrying the fix. There is deliberately no sixth step:
      a path that does not exist is better discovered here, in a millisecond,
      than by a run that has already committed the GPU.

      The answer is memoised PER TOOL for the process, and the memo is
      ENFORCED rather than merely offered: the first resolution wins, a later
      -Explicit naming the same file is accepted, and a later -Explicit that
      resolves to a DIFFERENT usable binary throws with both paths in the
      message. So the ladder cannot measure rung 1 with one build and rung 7
      with another - whether the second answer arrives from an environment
      variable edited mid-run or from a caller's hint - and the ladder ranks
      rungs against each other, which is a comparison that means nothing
      across two toolchains. A hint that does not resolve, because the file is
      missing or the binary is foreign to this OS, is skipped exactly as the
      chain skips it anywhere else, and the memo stands.
    #>
    param([Parameter(Mandatory = $true)][string]$Tool, [string]$Explicit)
    if ($Tool.EndsWith('.exe')) { $Tool = $Tool.Substring(0, $Tool.Length - 4) }
    $memo = $script:LlamaToolBin[$Tool]
    if ($memo) {
        if ($Explicit) {
            $want = $null
            if ((Test-Path -LiteralPath $Explicit -PathType Leaf) -and
                (-not (Get-BinaryMismatch $Explicit))) {
                $want = (Resolve-Path -LiteralPath $Explicit).Path
            }
            if ($want -and ($want -ne $memo)) {
                throw ("{0}: this process already resolved`n  {1}`nand has now been handed`n  {2}`n" -f $Tool, $memo, $want) +
                      ("as a hint. One run measures with ONE toolchain: the rungs are ranked against each other " +
                       "and that comparison does not survive a build swapped mid-run (rule 3). Start a fresh " +
                       "run for the other build, or pass the same one everywhere.")
            }
        }
        return $memo
    }

    # $PSScriptRoot inside a function is the directory of the file the function
    # was DEFINED in - this one - no matter which script dot-sourced it, so the
    # archived work/*.ps1 runners that dot-source this library by absolute path
    # still find the repo they are part of.
    $repoBin = Join-Path (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path 'bin\llama.cpp'
    $steps = @()
    $steps += @{ via = "the caller's hint"; cands = @($Explicit) }
    if ($Tool -eq 'llama-server') {
        $steps += @{ via = '$env:LLAMA_SERVER'; cands = @($env:LLAMA_SERVER) }
    }
    $steps += @{ via = '$env:LLAMA_DIR'; cands = $(if ($env:LLAMA_DIR) { Get-LlamaToolCandidates $env:LLAMA_DIR $Tool } else { @() }) }
    $steps += @{ via = 'PATH'; cands = $(
        $g = Get-Command $Tool -CommandType Application -ErrorAction SilentlyContinue
        if ($g) { @(($g | Select-Object -First 1).Source) } else { @() }) }
    $steps += @{ via = '<repo>\bin\llama.cpp'; cands = (Get-LlamaToolCandidates $repoBin $Tool) }

    $tried = @()
    $hit = $null
    $via = ''
    foreach ($s in $steps) {
        foreach ($c in $s.cands) {
            if (-not $c) { continue }
            if (-not (Test-Path -LiteralPath $c -PathType Leaf)) { $tried += $c; continue }
            $why = Get-BinaryMismatch $c
            if ($why) {
                # Keep looking: a usable build further down the chain still
                # wins, and if none is found the list below names this one and
                # says exactly what is wrong with it.
                $tried += ('{0}   <-- SKIPPED: {1}' -f $c, $why)
                continue
            }
            $tried += $c
            $hit = (Resolve-Path -LiteralPath $c).Path
            $via = $s.via
            break
        }
        if ($hit) { break }
    }

    if (-not $hit) {
        $looked = $(if ($tried.Count) { ($tried -join "`n  ") } else { '(nowhere - no candidates)' })
        throw ("{0} not found. Any one of these fixes it:`n" -f $Tool) +
              ("  .\scripts\setup.ps1              bootstraps llama.cpp into <repo>\bin\llama.cpp\`n" +
               "  `$env:LLAMA_DIR    = '<dir>'      a directory holding the llama.cpp tools`n" +
               "  `$env:LLAMA_SERVER = '<file>'     the llama-server binary itself (llama-server only)`n" +
               "Looked at:`n  $looked`n" +
               "This launcher is the PowerShell half of scripts\lib\paths.py's chain; that " +
               "module also reads results\<slug>\campaign.json `"llama_dir`", which this one " +
               "cannot.`nRun  python scripts\lib\paths.py  to see what resolves on this machine.")
    }
    $script:LlamaToolBin[$Tool] = $hit
    Write-Log ('{0}: {1}  (resolved via {2})' -f $Tool, $hit, $via)
    return $hit
}

function Get-LlamaServerBin {
    # The llama-server binary. Its own name because it is what every probe
    # launcher here asks for, and because reference/platform-notes.md names
    # this function as the answer to "which llama.cpp will this run use".
    param([string]$Explicit)
    return Get-LlamaToolBin -Tool 'llama-server' -Explicit $Explicit
}

function Stop-Srv {
    try { Get-Process llama-server -ErrorAction Stop | Stop-Process -Force -Confirm:$false } catch {}
    Start-Sleep -Seconds 3
}

function Start-Srv {
    param([string]$ModelPath, [string]$Tag, [string[]]$Flags, [int]$Port,
          [string]$LogDir, [int]$TimeoutSec = 900, [string]$ServerBin)
    # Resolve BEFORE Stop-Srv, and before anything is killed or written: a
    # toolchain this machine does not have is a fact about the MACHINE, and it
    # must not arrive dressed as a rung that failed.
    $exe = Get-LlamaServerBin -Explicit $ServerBin
    Stop-Srv
    $errLog = Join-Path $LogDir ('srv-{0}.err.log' -f $Tag)
    $outLog = Join-Path $LogDir ('srv-{0}.out.log' -f $Tag)
    Remove-Item $errLog, $outLog -ErrorAction SilentlyContinue
    $a = @('-m', $ModelPath, '--alias', 'ladder', '--host', '127.0.0.1', '--port', "$Port") + $Flags
    $sw = [Diagnostics.Stopwatch]::StartNew()
    $proc = Start-GuardedServer -FilePath $exe -ArgumentList $a `
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
