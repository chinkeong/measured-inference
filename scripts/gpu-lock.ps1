# One GPU job at a time, for the PowerShell launchers.
#
# The PowerShell twin of scripts/bench/gpu_lock.py, sharing the SAME lockfile,
# so a .ps1 arm and a .py probe cannot both hold the GPU. Read that module's
# header for the incident this exists to prevent (2026-08-29 host OOM: four
# llama-server processes, ~53 GB wanted on a 59.8 GB commit limit, no
# bluescreen, power button).
#
# Dot-source it, then take the lock before you start anything:
#
#     . "$PSScriptRoot\..\gpu-lock.ps1"
#     Enter-GpuLock -Tag 'quant-ladder'
#     try   { $p = Start-GuardedServer -FilePath $exe -ArgumentList $a ... }
#     finally { Exit-GpuLock }
#
# WHY NOT JUST `Get-Process llama-server`. That check (which several scripts
# here already had) catches a live server but not the window between "I decided
# to start" and "my server appears in the process list", and it says nothing
# about a Python probe that is three seconds from launching one. The lockfile
# closes both. It is also what makes `Get-Process llama-server | Stop-Process`
# safe: past Enter-GpuLock, anything still running IS an orphan.
#
# PowerShell 5.1 compatible: no &&, no ternary, no ?. — see
# reference/platform-notes.md.

$script:GpuLockPath = $env:MEASURED_INFERENCE_LOCK
if (-not $script:GpuLockPath) {
    $script:GpuLockPath = Join-Path (Resolve-Path (Join-Path $PSScriptRoot "..")).Path ".gpu-lock.json"
}
$script:GpuLockHeld = $false
$script:GpuJobs = @()

# Per-job commit cap and the refuse-to-launch threshold. Keep these in step
# with MEM_CAP_FRAC / COMMIT_REFUSE_FRAC in gpu_lock.py.
$script:GpuMemCapFrac = 0.75
$script:GpuCommitRefuseFrac = 0.55

Add-Type -ErrorAction SilentlyContinue -TypeDefinition @'
using System;
using System.Runtime.InteropServices;

public static class MiJob {
    [StructLayout(LayoutKind.Sequential)]
    public struct IO_COUNTERS {
        public ulong Read, Write, Other, ReadX, WriteX, OtherX;
    }
    [StructLayout(LayoutKind.Sequential)]
    public struct JOBOBJECT_BASIC_LIMIT_INFORMATION {
        public long PerProcessUserTimeLimit, PerJobUserTimeLimit;
        public uint LimitFlags;
        public UIntPtr MinimumWorkingSetSize, MaximumWorkingSetSize;
        public uint ActiveProcessLimit;
        public UIntPtr Affinity;
        public uint PriorityClass, SchedulingClass;
    }
    [StructLayout(LayoutKind.Sequential)]
    public struct JOBOBJECT_EXTENDED_LIMIT_INFORMATION {
        public JOBOBJECT_BASIC_LIMIT_INFORMATION BasicLimitInformation;
        public IO_COUNTERS IoInfo;
        public UIntPtr ProcessMemoryLimit, JobMemoryLimit;
        public UIntPtr PeakProcessMemoryUsed, PeakJobMemoryUsed;
    }

    const uint JOB_OBJECT_LIMIT_JOB_MEMORY        = 0x00000200;
    const uint JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 0x00002000;

    [DllImport("kernel32.dll", CharSet = CharSet.Unicode, SetLastError = true)]
    static extern IntPtr CreateJobObject(IntPtr a, string name);
    [DllImport("kernel32.dll", SetLastError = true)]
    static extern bool SetInformationJobObject(IntPtr job, int cls, IntPtr info, uint len);
    [DllImport("kernel32.dll", SetLastError = true)]
    static extern bool AssignProcessToJobObject(IntPtr job, IntPtr proc);

    // Returns the job handle. Keep it alive: closing it kills the child, which
    // is exactly the orphan guarantee we want.
    public static IntPtr CapAndOwn(IntPtr processHandle, ulong memLimitBytes) {
        IntPtr job = CreateJobObject(IntPtr.Zero, null);
        if (job == IntPtr.Zero) return IntPtr.Zero;
        var info = new JOBOBJECT_EXTENDED_LIMIT_INFORMATION();
        info.BasicLimitInformation.LimitFlags =
            JOB_OBJECT_LIMIT_JOB_MEMORY | JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE;
        info.JobMemoryLimit = new UIntPtr(memLimitBytes);
        int len = Marshal.SizeOf(typeof(JOBOBJECT_EXTENDED_LIMIT_INFORMATION));
        IntPtr p = Marshal.AllocHGlobal(len);
        try {
            Marshal.StructureToPtr(info, p, false);
            if (!SetInformationJobObject(job, 9, p, (uint)len)) return IntPtr.Zero;
        } finally { Marshal.FreeHGlobal(p); }
        if (!AssignProcessToJobObject(job, processHandle)) return IntPtr.Zero;
        return job;
    }
}
'@

function Get-GpuMemoryStatus {
    $os = Get-CimInstance Win32_OperatingSystem
    $cs = Get-CimInstance Win32_ComputerSystem
    $limit = [double]$os.TotalVirtualMemorySize * 1KB      # commit limit
    [pscustomobject]@{
        TotalPhys   = [double]$cs.TotalPhysicalMemory
        CommitLimit = $limit
        CommitUsed  = $limit - ([double]$os.FreeVirtualMemory * 1KB)
    }
}

function Get-GpuMemCapBytes {
    if ($env:MEASURED_INFERENCE_MEM_CAP_GB) {
        return [uint64]([double]$env:MEASURED_INFERENCE_MEM_CAP_GB * 1GB)
    }
    [uint64]((Get-GpuMemoryStatus).TotalPhys * $script:GpuMemCapFrac)
}

function Get-LiveLlamaServers {
    @(Get-Process -Name 'llama-server' -ErrorAction SilentlyContinue)
}

function Get-GpuLockHolder {
    if (-not (Test-Path $script:GpuLockPath)) { return $null }
    try { $rec = Get-Content $script:GpuLockPath -Raw | ConvertFrom-Json } catch { return $null }
    if (-not $rec.pid) { return $null }
    $p = Get-Process -Id $rec.pid -ErrorAction SilentlyContinue
    if (-not $p) { return $null }   # dead holder: the lock is a corpse
    return $rec
}

function Enter-GpuLock {
    <#
      Take the machine-wide GPU lock. Throws if someone else holds it, or if a
      llama-server we did not start is already live.
        -WaitSeconds     keep retrying instead of failing fast
        -AllowForeign    don't refuse an existing server (for attach-only runs)
    #>
    param([Parameter(Mandatory=$true)][string]$Tag,
          [int]$WaitSeconds = 0,
          [switch]$AllowForeign)

    if ($script:GpuLockHeld) { return }
    $deadline = (Get-Date).AddSeconds($WaitSeconds)
    while ($true) {
        $cur = Get-GpuLockHolder
        if (-not $cur) {
            if (Test-Path $script:GpuLockPath) {
                Remove-Item $script:GpuLockPath -Force -ErrorAction SilentlyContinue
            }
            # start_time stays null on purpose: gpu_lock.py treats null as
            # "cannot verify, trust PID liveness", which never steals a live
            # lock. Claiming a start_time we compute differently could.
            $rec = [pscustomobject]@{
                pid        = $PID
                start_time = $null
                tag        = $Tag
                argv       = $(
                    $c = $null
                    if ((Get-PSCallStack).Count -gt 1) { $c = (Get-PSCallStack)[1].ScriptName }
                    if ($c) { $c } else { $Tag })
                host       = $env:COMPUTERNAME
                acquired   = (Get-Date -Format 'yyyy-MM-ddTHH:mm:ss')
            }
            $rec | ConvertTo-Json | Out-File -FilePath $script:GpuLockPath -Encoding utf8
            Start-Sleep -Milliseconds 150          # let a racing writer land
            $back = Get-GpuLockHolder
            if ($back -and $back.pid -eq $PID) {
                $script:GpuLockHeld = $true
                break
            }
            continue
        }
        if ((Get-Date) -ge $deadline) {
            throw ("another GPU job holds the lock - rule 20, one GPU job at a time.`n" +
                   "  holder : pid $($cur.pid), tag '$($cur.tag)', since $($cur.acquired)`n" +
                   "  command: $($cur.argv)`n" +
                   "  lock   : $script:GpuLockPath`n" +
                   "Wait for it, or if you are sure it is dead:  python scripts\bench\gpu_lock.py kill")
        }
        Start-Sleep -Seconds 2
    }

    if (-not $AllowForeign) {
        $live = Get-LiveLlamaServers
        if ($live) {
            Exit-GpuLock
            throw ("llama-server is already running (pid $($live.Id -join ', ')) and this " +
                   "script did not start it.`n" +
                   "Starting an arm on top of another arm's weights silently mislabels every " +
                   "result, and two resident models is how the 2026-08-29 host OOM happened.`n" +
                   "Stop it first:  python scripts\bench\gpu_lock.py kill")
        }
    }
}

function Exit-GpuLock {
    if (-not $script:GpuLockHeld) { return }
    $cur = Get-GpuLockHolder
    if ($cur -and $cur.pid -eq $PID) {
        Remove-Item $script:GpuLockPath -Force -ErrorAction SilentlyContinue
    }
    $script:GpuLockHeld = $false
}

function Assert-GpuHeadroom {
    param([uint64]$Cap = 0)
    if ($Cap -eq 0) { $Cap = Get-GpuMemCapBytes }
    $m = Get-GpuMemoryStatus
    if ($m.CommitUsed -gt $m.CommitLimit * $script:GpuCommitRefuseFrac) {
        throw ("system commit is already {0:N1} GB of {1:N1} GB ({2:N0}%) - refusing to load a " +
               "model into that. Find what is holding memory before starting a run, or the host " +
               "hangs and the campaign dies with it." -f
               ($m.CommitUsed/1GB), ($m.CommitLimit/1GB), (100*$m.CommitUsed/$m.CommitLimit))
    }
    if ($m.CommitUsed + $Cap -gt $m.CommitLimit * 0.90) {
        throw ("commit headroom too small: {0:N1} GB free of a {1:N1} GB limit, and this job is " +
               "capped at {2:N1} GB. Free memory, or lower the cap with " +
               "MEASURED_INFERENCE_MEM_CAP_GB (and record the change - it is a condition, rule 3)." -f
               (($m.CommitLimit-$m.CommitUsed)/1GB), ($m.CommitLimit/1GB), ($Cap/1GB))
    }
}

function Start-GuardedServer {
    <#
      Start-Process for a llama-server - or any other child that loads a model
      and can therefore exhaust host commit, llama-perplexity included - with
      the guards attached: headroom preflight, a commit cap, and a job object
      that kills the child when THIS PowerShell process exits. Same parameters
      as Start-Process -PassThru, and it returns the same Process object.

      A .bat or cmd.exe wrapper is fine: child processes inherit the job, so
      the cap and the kill-on-close cover the whole tree, not just the shim.

      -Detached opts out of the job object for a server that is deliberately
      meant to outlive this script. Nothing in this repo should need it.
    #>
    param([Parameter(Mandatory=$true)][string]$FilePath,
          [string[]]$ArgumentList = @(),
          [string]$RedirectStandardOutput,
          [string]$RedirectStandardError,
          [string]$WindowStyle = 'Hidden',
          [switch]$NoNewWindow,
          [string]$WorkingDirectory,
          [uint64]$Cap = 0,
          [switch]$Detached,
          # Accepted and ignored: this function always passes the process
          # through, and taking the switch keeps it a drop-in for the
          # Start-Process calls it replaced.
          [switch]$PassThru)

    # Auto-acquire, matching gpu_lock.serve()'s behaviour on the Python side: a
    # caller that forgot the lock gets it here rather than getting an exception
    # it might "fix" by deleting the guard. Deliberately sticky - it is held
    # until Exit-GpuLock or this process dies, so a script that stops one
    # server and starts another is still ONE job and nobody races into the gap.
    if (-not $script:GpuLockHeld) {
        $auto = $null
        if ((Get-PSCallStack).Count -gt 1) { $auto = (Get-PSCallStack)[1].ScriptName }
        if ($auto) { $auto = [IO.Path]::GetFileNameWithoutExtension($auto) } else { $auto = 'gpu-job' }
        Enter-GpuLock -Tag $auto
    }
    if ($Cap -eq 0) { $Cap = Get-GpuMemCapBytes }
    Assert-GpuHeadroom -Cap $Cap

    $sp = @{ FilePath = $FilePath; ArgumentList = $ArgumentList; PassThru = $true }
    # Start-Process rejects both at once, so NoNewWindow wins when given.
    if ($NoNewWindow) { $sp['NoNewWindow'] = $true } else { $sp['WindowStyle'] = $WindowStyle }
    if ($RedirectStandardOutput) { $sp['RedirectStandardOutput'] = $RedirectStandardOutput }
    if ($RedirectStandardError)  { $sp['RedirectStandardError']  = $RedirectStandardError }
    if ($WorkingDirectory)       { $sp['WorkingDirectory']       = $WorkingDirectory }
    $proc = Start-Process @sp

    if (-not $Detached) {
        try {
            $job = [MiJob]::CapAndOwn($proc.Handle, $Cap)
            if ($job -eq [IntPtr]::Zero) {
                Write-Warning ("gpu-lock: could not job-cap llama-server pid $($proc.Id); it is " +
                               "uncapped and may outlive this script. Watch it.")
            } else {
                $script:GpuJobs += $job
            }
        } catch {
            Write-Warning "gpu-lock: job object failed for pid $($proc.Id): $($_.Exception.Message)"
        }
    }
    return $proc
}

function Get-GpuLockStatus {
    $m = Get-GpuMemoryStatus
    Write-Output ("memory : {0:N1} GB RAM | commit {1:N1} / {2:N1} GB ({3:N0}%) | per-job cap {4:N1} GB" -f
                  ($m.TotalPhys/1GB), ($m.CommitUsed/1GB), ($m.CommitLimit/1GB),
                  (100*$m.CommitUsed/$m.CommitLimit), ((Get-GpuMemCapBytes)/1GB))
    Write-Output ("lock   : $script:GpuLockPath")
    $cur = Get-GpuLockHolder
    if ($cur) {
        Write-Output ("         HELD by pid $($cur.pid), tag '$($cur.tag)', since $($cur.acquired)")
        Write-Output ("         $($cur.argv)")
    } else {
        Write-Output "         free"
    }
    $live = Get-LiveLlamaServers
    if ($live) { Write-Output ("servers: $($live.Count) LIVE - pid " + ($live.Id -join ', ')) }
    else       { Write-Output "servers: none" }
}
