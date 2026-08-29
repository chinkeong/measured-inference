#Requires -Version 5.1
<#
.SYNOPSIS
Bootstrap a self-contained llama.cpp into <repo>\bin\llama.cpp\ plus the Python
venv the harness runs in -- no admin, nothing outside the repo tree.

.DESCRIPTION
The POSIX twin is scripts/setup.sh; the two write the SAME bin/llama.cpp/INSTALL.json
schema, run the same frozen-input byte check, and create the same .venv, so a
campaign rerun under Ubuntu can be compared field-by-field against a Windows one.

Windows does have official CUDA binaries, so the NVIDIA path here is a download,
not a source build. What it shares with setup.sh is the refusal: if an NVIDIA GPU
is present and the backend on offer is NOT CUDA, this exits non-zero instead of
quietly installing a Vulkan or CPU build. The backend is a condition of every
number (METHODOLOGY rule 3); swapping it silently makes a rerun incomparable to
the campaign it is rerunning.

.EXAMPLE
.\scripts\setup.ps1
.EXAMPLE
.\scripts\setup.ps1 -Publish -Tag b10582
.EXAMPLE
.\scripts\setup.ps1 -DryRun
#>
param(
    [switch]$Force,        # reinstall even if this release+flavor is already present
    [switch]$Publish,      # install requirements.txt (plots/stats) instead of requirements-min.txt
    [switch]$NoVenv,       # skip the .venv step entirely
    [switch]$AllowVulkan,  # accept a non-CUDA backend on an NVIDIA GPU, deliberately
    [switch]$DryRun,       # detect, decide, print the plan; touch nothing
    [string]$Tag,          # pin a llama.cpp release (bNNNNN) instead of taking the newest
    [switch]$Help
)
$ErrorActionPreference = 'Stop'

# ---- Asset name patterns (regex, matched against release asset names) --------------------------
# Verified against release b10582 (2026-08-22). Names drift between releases; fix here if selection fails.
# CUDA 12.4 chosen over the also-published 13.3 for wider driver compatibility (fine for RTX 3090).
$PatCuda   = '^llama-b\d+-bin-win-cuda-12\.4-x64\.zip$'    # Windows x64 CUDA build
$PatCudart = '^cudart-llama-bin-win-cuda-12\.4-x64\.zip$'  # CUDA runtime DLLs -- REQUIRED companion, same CUDA ver
$PatVulkan = '^llama-b\d+-bin-win-vulkan-x64\.zip$'        # Intel/AMD GPUs
$PatCpu    = '^llama-b\d+-bin-win-cpu-x64\.zip$'           # no-GPU fallback
$TagRegex  = '^b\d+$'  # binary releases are tagged bNNNNN; /releases/latest points elsewhere (v0.2.0 nightly tracker) -- do not use it
# Every llama.cpp tool this repo shells out to; recorded in INSTALL.json so a
# stage that needs llama-mtmd-cli can check before it spends an hour finding out.
$WantedTools = @('llama-server.exe', 'llama-perplexity.exe', 'llama-cli.exe',
                 'llama-bench.exe', 'llama-tokenize.exe', 'llama-mtmd-cli.exe')
# ------------------------------------------------------------------------------------------------

$RepoRoot    = Split-Path -Parent $PSScriptRoot
$Dest        = Join-Path $RepoRoot 'bin\llama.cpp'
$DlDir       = Join-Path $Dest '.downloads'
$VersionFile = Join-Path $Dest 'VERSION.txt'
$InstallJson = Join-Path $Dest 'INSTALL.json'
$Exe         = Join-Path $Dest 'llama-server.exe'

function Write-Info { param([string]$Msg) Write-Host "[setup] $Msg" }
function Write-Warn { param([string]$Msg) Write-Host "[setup] WARNING: $Msg" -ForegroundColor Yellow }

function Show-Usage {
    Write-Host @'
Usage: .\scripts\setup.ps1 [options]

  -Force         reinstall even if this release+flavor is already present
  -Publish       install requirements.txt (plots/stats) instead of requirements-min.txt
  -NoVenv        skip the .venv step entirely (you manage Python yourself)
  -AllowVulkan   accept a non-CUDA backend on an NVIDIA GPU (see below)
  -DryRun        detect, decide and print the plan; touch nothing, download nothing
  -Tag bNNNNN    pin a llama.cpp release instead of taking the newest one.
                 Pin it when a rerun must match an earlier campaign's build
  -Help          this text

Environment:
  MEASURED_INFERENCE_ALLOW_VULKAN=1  same as -AllowVulkan
  MEASURED_INFERENCE_ALLOW_CRLF=1    proceed even if a frozen input no longer
                                     matches its committed bytes (CRLF rewriting)
  MEASURED_INFERENCE_DRY_RUN=1       same as -DryRun (the gpu_lock convention)

On an NVIDIA GPU, any backend other than CUDA changes every throughput number for
a reason unrelated to the model, so setup EXITS NON-ZERO rather than installing
one quietly. POSIX twin: scripts/setup.sh (same INSTALL.json, same checks).
'@
}
if ($Help) { Show-Usage; exit 0 }

if ($env:MEASURED_INFERENCE_ALLOW_VULKAN -eq '1') { $AllowVulkan = $true }
if ($env:MEASURED_INFERENCE_DRY_RUN -eq '1')      { $DryRun = $true }
$AllowCrlf = ($env:MEASURED_INFERENCE_ALLOW_CRLF -eq '1')
if ($Tag -and $Tag -notmatch $TagRegex) { throw "-Tag '$Tag' does not look like a llama.cpp binary release (bNNNNN)." }
if ($DryRun) { Write-Info 'DRY RUN: nothing is downloaded, written or installed.' }

# ------------------------------------------------- 1. frozen inputs, byte-exact
# Git-for-Windows installs with core.autocrlf=true. A clone made before
# .gitattributes existed has every LF in corpora\wikitext-2-raw-test.raw rewritten
# to CRLF -- 1,290,590 bytes become 1,294,948 -- and the quant ranking (rule 6,
# perplexity over 294,912 token positions) is then computed over a different file
# than the published one. Same hazard for the frozen datasets and rule 23's hashes.
#
# The test is byte size against the COMMITTED blob, not "does it contain CR": one
# frozen input, meetingbank_test.jsonl, is legitimately CRLF in git, and a
# CR-hunting heuristic would condemn it on every platform.
function Test-FrozenInputs {
    if (-not (Test-Path (Join-Path $RepoRoot '.gitattributes'))) {
        Write-Warn "no .gitattributes at the repo root -- '* -text' is what stops a Windows clone rewriting the frozen inputs."
    }
    # .git first: asking git about a non-repo prints "fatal:" to stderr, and in
    # 5.1 redirecting a native command's stderr wraps every line in an
    # ErrorRecord (reference/platform-notes.md). Cheaper to not ask.
    if (-not (Get-Command git -ErrorAction SilentlyContinue) -or
        -not (Test-Path (Join-Path $RepoRoot '.git'))) {
        Write-Info 'Frozen inputs: NOT VERIFIED -- no git metadata here to compare the bytes against.'
        return 'unverified'
    }
    $prev = $ErrorActionPreference; $ErrorActionPreference = 'Continue'
    try {
        $files = & git -C $RepoRoot ls-files -- corpora scripts/bench/datasets-frozen
        if ($LASTEXITCODE -ne 0) {
            Write-Info 'Frozen inputs: NOT VERIFIED -- no git metadata here to compare the bytes against.'
            return 'unverified'
        }
        $bad = @(); $checked = 0
        foreach ($rel in $files) {
            if (-not $rel) { continue }
            $full = Join-Path $RepoRoot ($rel -replace '/', '\')
            if (-not (Test-Path -LiteralPath $full)) { continue }
            $want = & git -C $RepoRoot cat-file -s "HEAD:$rel"
            if ($LASTEXITCODE -ne 0 -or -not $want) { continue }
            $got = (Get-Item -LiteralPath $full).Length
            $checked++
            if ([int64]$want -ne [int64]$got) {
                $bad += "$rel (committed $want bytes, on disk $got)"
            }
        }
    } finally { $ErrorActionPreference = $prev }

    if ($bad.Count -eq 0) {
        Write-Info "Frozen inputs: $checked files byte-identical to their commit."
        return 'match'
    }
    foreach ($b in $bad) { Write-Warn "frozen input does not match its commit: $b" }
    if ($AllowCrlf) {
        Write-Warn 'MEASURED_INFERENCE_ALLOW_CRLF=1 -- continuing with rewritten inputs. No perplexity or suite hash from this clone is comparable to a published one.'
        return 'rewritten'
    }
    Write-Host @"
[setup] These bytes are data, not formatting, and this checkout no longer matches
[setup] what was committed -- the usual cause is git core.autocrlf rewriting LF to
[setup] CRLF on a Windows clone. Perplexity here would be computed over a different
[setup] file than the published ranking was (rule 6), and suite hashes will not
[setup] match (rule 23).
[setup] Fix, from $RepoRoot :
[setup]     git config core.autocrlf false
[setup]     git rm --cached -r . > `$null; git reset --hard
[setup] Then re-run this script. Override with MEASURED_INFERENCE_ALLOW_CRLF=1 only
[setup] if no perplexity or dataset number from this clone will ever be published.
"@
    exit 5
}
$FrozenState = Test-FrozenInputs

# --------------------------------------------------- 2. detect GPU and flavor
$gpuNames = ''
try { $gpuNames = ((Get-CimInstance Win32_VideoController -ErrorAction Stop).Name) -join '; ' } catch { $gpuNames = '' }
$hasSmi = [bool](Get-Command nvidia-smi -ErrorAction SilentlyContinue)
$gpu = 'none'; $gpuName = $null; $driver = $null
if ($hasSmi -or $gpuNames -match 'NVIDIA|GeForce|Quadro|Tesla|RTX') {
    $gpu = 'nvidia'
    if ($hasSmi) {
        $q = (& nvidia-smi --query-gpu=name,driver_version --format=csv,noheader | Select-Object -First 1)
        if ($q) { $parts = $q -split ',\s*'; $gpuName = $parts[0]; if ($parts.Count -gt 1) { $driver = $parts[1] } }
    } else {
        $gpuName = $gpuNames
        Write-Warn 'an NVIDIA GPU is present but nvidia-smi is not on PATH -- the harness reads VRAM, clocks and power through it (rules 13, 24). Install/repair the driver before measuring.'
    }
} elseif ($gpuNames -match 'Intel|AMD|Radeon|Arc') {
    $gpu = 'vulkan-capable'; $gpuName = $gpuNames
}
$flavor = switch ($gpu) { 'nvidia' { 'cuda' } 'vulkan-capable' { 'vulkan' } default { 'cpu' } }
$arch = switch ($env:PROCESSOR_ARCHITECTURE) { 'AMD64' { 'x86_64' } 'ARM64' { 'aarch64' } default { $env:PROCESSOR_ARCHITECTURE } }
Write-Info "os=Windows arch=$arch gpu=$gpu$(if ($gpuName) { " ($gpuName$(if ($driver) { ", driver $driver" }))" })"
Write-Info "backend flavor: $flavor"

# ---------------------------- 3. THE GATE: no silent backend substitution
if ($gpu -eq 'nvidia' -and $flavor -ne 'cuda') {
    if ($AllowVulkan) {
        Write-Warn "NVIDIA GPU with a '$flavor' build (-AllowVulkan / MEASURED_INFERENCE_ALLOW_VULKAN=1)."
        Write-Warn "Every number this produces is a '$flavor' number. Say so in campaign.md and in the report; it is NOT comparable to a CUDA campaign."
    } else {
        Write-Host @"
[setup] ERROR: NVIDIA GPU detected, but the backend on offer is '$flavor', not CUDA.
[setup] Installing it would hand you a working server whose every throughput,
[setup] acceptance and VRAM number differs from a CUDA campaign's for a reason that
[setup] has nothing to do with the model -- and nothing in the run would tell you
[setup] (rule 3). Fix the CUDA asset patterns at the top of this script, or take the
[setup] other backend deliberately and on the record:
[setup]     .\scripts\setup.ps1 -AllowVulkan
"@
        exit 3
    }
}

# ------------------------------------------------------ 4. resolve the release
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
$headers = @{ 'User-Agent' = 'measured-inference-setup'; 'Accept' = 'application/vnd.github+json' }
$rel = $null
# $relTag, not $tag: PowerShell is case-insensitive, so $tag WOULD BE the -Tag
# parameter, and every later assignment would quietly overwrite what the caller asked for.
if ($Tag) {
    Write-Info "Release pinned by -Tag: $Tag"
    $relTag = $Tag
} elseif ($DryRun) {
    $relTag = '<newest-bNNNNN>'
    Write-Info 'Would query the GitHub API for the newest bNNNNN release.'
} else {
    $releases = Invoke-RestMethod -Uri 'https://api.github.com/repos/ggml-org/llama.cpp/releases?per_page=10' -Headers $headers
    $rel = $releases | Where-Object { $_.tag_name -match $TagRegex -and $_.assets.Count -gt 0 } | Select-Object -First 1
    if (-not $rel) { throw "No bNNNNN release with assets found in the 10 most recent releases -- check `$TagRegex." }
    $relTag = $rel.tag_name
    Write-Info "Latest binary release: $relTag"
}

# -------------------------------------------------------------- 5. idempotency
# INSTALL.json is part of the install, not a note about it: an install that cannot
# say which backend it is has to be redone (rule 3).
$installedFlavor = $null
if (Test-Path $InstallJson) {
    try { $installedFlavor = (Get-Content $InstallJson -Raw | ConvertFrom-Json).flavor } catch { $installedFlavor = $null }
}
$skipInstall = $false
if (-not $Force -and (Test-Path $VersionFile) -and (Test-Path $Exe) -and
    ((Get-Content $VersionFile -TotalCount 1).Trim() -eq $relTag)) {
    if ($installedFlavor -eq $flavor) {
        $skipInstall = $true
        Write-Info "$relTag ($flavor) already installed at $Dest -- skipping the install (use -Force to redo it)."
    } elseif (-not $installedFlavor) {
        Write-Info "$relTag is installed but INSTALL.json records no flavor -- reinstalling so the backend goes on the record."
    } else {
        Write-Info "$relTag is installed as '$installedFlavor', you asked for '$flavor' -- reinstalling."
    }
}

# ------------------------------------------------------------- 6. the dry run
if ($DryRun) {
    Write-Host ''
    Write-Info '--- plan ---'
    if ($skipInstall) {
        Write-Info "install : skip ($relTag / $flavor already present)"
    } else {
        $wantedPats = if ($flavor -eq 'cuda') { "$PatCuda + $PatCudart" } elseif ($flavor -eq 'vulkan') { $PatVulkan } else { $PatCpu }
        Write-Info "install : binary release -> $Dest"
        Write-Info "          assets matching: $wantedPats"
    }
    Write-Info "record  : $InstallJson  (tag, flavor=$flavor, arch=$arch, os, assets, urls, installed_utc, built_from_source, cuda_arch)"
    if ($NoVenv) { Write-Info 'python  : skipped (-NoVenv)' }
    else { Write-Info "python  : $RepoRoot\.venv + $(if ($Publish) { 'requirements.txt' } else { 'requirements-min.txt' })" }
    Write-Info '--- end of plan; nothing was changed ---'
    exit 0
}

# ------------------------------------------------------- 7. download + extract
$assetNames = @(); $assetUrls = @()
if (-not $skipInstall) {
    if (-not $rel) {
        $rel = Invoke-RestMethod -Uri "https://api.github.com/repos/ggml-org/llama.cpp/releases/tags/$relTag" -Headers $headers
    }
    if ($flavor -eq 'cuda')       { $wanted = @($PatCuda, $PatCudart) }
    elseif ($flavor -eq 'vulkan') { $wanted = @($PatVulkan) }
    else                          { $wanted = @($PatCpu) }
    $assets = @()
    foreach ($pat in $wanted) {
        $a = $rel.assets | Where-Object { $_.name -match $pat } | Select-Object -First 1
        if (-not $a) { throw "No asset in $relTag matches pattern '$pat' -- release naming drifted; update the patterns at the top of this script." }
        $assets += $a
    }

    New-Item -ItemType Directory -Force -Path $Dest, $DlDir | Out-Null
    $curl = Get-Command curl.exe -ErrorAction SilentlyContinue
    foreach ($a in $assets) {
        $zip = Join-Path $DlDir $a.name
        Write-Info "Downloading $($a.name) ($([math]::Round($a.size/1MB,1)) MB)..."
        if ($curl) {
            & $curl.Source -fL -C - --retry 3 --retry-delay 2 -o $zip $a.browser_download_url
            if ($LASTEXITCODE -ne 0) { & $curl.Source -fL --retry 3 -o $zip $a.browser_download_url }  # resume unsupported -> fresh
            if ($LASTEXITCODE -ne 0) { throw "Download failed: $($a.browser_download_url)" }
        } else {
            Invoke-WebRequest -Uri $a.browser_download_url -OutFile $zip -Headers @{ 'User-Agent' = 'measured-inference-setup' }
        }
        Write-Info "Extracting $($a.name)..."
        Expand-Archive -Path $zip -DestinationPath $Dest -Force   # win zips are flat: exes/DLLs land in $Dest
        Remove-Item $zip -Force -Confirm:$false
        $assetNames += $a.name
        $assetUrls  += $a.browser_download_url
    }
}

# ----------------------------------------------------------- 8. verify it runs
if (-not (Test-Path $Exe)) { throw "llama-server.exe not found in $Dest after extraction." }
$verOut = & cmd /c "`"$Exe`" --version 2>&1"
if ($LASTEXITCODE -ne 0) { throw "llama-server.exe --version failed (exit $LASTEXITCODE): $verOut" }
$verLine = (($verOut | Select-Object -First 2) -join ' | ')
Set-Content -Path $VersionFile -Value $relTag -Encoding ascii

# ------------------------------------------- 9. INSTALL.json: what this IS
# $flavor used to be computed and thrown away, so no report could state whether
# its numbers were CUDA, Vulkan or CPU -- rule 3's strongest condition, unrecorded.
# Written the moment it is known (rule 28), in the same schema setup.sh writes.
$tools = @($WantedTools | Where-Object { Test-Path (Join-Path $Dest $_) })
$osDesc = "$((Get-CimInstance Win32_OperatingSystem).Caption) ($([Environment]::OSVersion.Version.ToString()))"
$record = [ordered]@{
    tag                        = $relTag
    flavor                     = $flavor
    arch                       = $arch
    # "os" is a TOKEN, not prose: scripts/detect-machine.py compares it against
    # {'win32':'windows','darwin':'macos'}.get(sys.platform,'linux') and treats
    # anything else as a build for a FOREIGN os, refusing to trust its flavor.
    os                         = 'windows'
    os_version                 = $osDesc
    host                       = $env:COMPUTERNAME
    assets                     = @($assetNames)
    urls                       = @($assetUrls)
    installed_utc              = (Get-Date).ToUniversalTime().ToString('yyyy-MM-ddTHH:mm:ssZ')
    built_from_source          = $false      # Windows has official CUDA binaries; setup.sh is the source-build path
    cuda_arch                  = $null
    gpu                        = $gpu
    gpu_name                   = $gpuName
    driver_version             = $driver
    server_version             = $verLine
    source_commit              = $null
    build_seconds              = $null
    tools                      = $tools
    needs_ld_library_path      = $false
    vulkan_override            = [bool]$AllowVulkan
    frozen_inputs_match_commit = $(switch ($FrozenState) { 'match' { $true } 'rewritten' { $false } default { $null } })
    installed_by               = 'scripts/setup.ps1'
}
# PS 5.1 Set-Content -Encoding utf8 writes a BOM, and json.load() on a BOM'd file
# raises JSONDecodeError -- every reader of this file is Python. UTF-8, no BOM, LF.
$json = (($record | ConvertTo-Json -Depth 4) -replace "`r`n", "`n") + "`n"
[IO.File]::WriteAllText($InstallJson, $json, (New-Object Text.UTF8Encoding($false)))
Write-Info "Recorded $InstallJson"

# ------------------------------------------------------------ 10. Python venv
$venvPy = $null; $reqName = $null
if ($NoVenv) {
    Write-Info 'Skipping the .venv step (-NoVenv).'
} else {
    $probe = 'import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)'
    $pyExe = $null; $pyArgs = @()
    foreach ($cand in @(@{E = 'py'; A = @('-3') }, @{E = 'python'; A = @() }, @{E = 'python3'; A = @() })) {
        $cmd = Get-Command $cand.E -ErrorAction SilentlyContinue
        if (-not $cmd) { continue }
        # the Microsoft Store stub answers to Get-Command but cannot run code
        & $cmd.Source @($cand.A + @('-c', $probe)) | Out-Null
        if ($LASTEXITCODE -eq 0) { $pyExe = $cmd.Source; $pyArgs = $cand.A; break }
    }
    if (-not $pyExe) {
        throw "No working Python 3.10+ found, and every collection script in this repo is Python. Install it from python.org (tick 'Add to PATH'), then re-run -- or pass -NoVenv if you manage Python yourself."
    }
    $venvPy = Join-Path $RepoRoot '.venv\Scripts\python.exe'
    if (-not (Test-Path $venvPy)) {
        Write-Info "Creating $RepoRoot\.venv with $pyExe..."
        & $pyExe @($pyArgs + @('-m', 'venv', (Join-Path $RepoRoot '.venv')))
        if ($LASTEXITCODE -ne 0) { throw "python -m venv failed (exit $LASTEXITCODE)." }
    }
    if (-not (Test-Path $venvPy)) { throw "no interpreter at $venvPy after creating the venv." }
    $reqName = if ($Publish) { 'requirements.txt' } else { 'requirements-min.txt' }
    $req = Join-Path $RepoRoot $reqName
    if (-not (Test-Path $req)) { throw "$req is missing." }
    Write-Info "Installing $reqName into .venv..."
    & $venvPy -m pip install --disable-pip-version-check -r $req
    if ($LASTEXITCODE -ne 0) { throw "pip install -r $req failed (exit $LASTEXITCODE). Offline? Re-run with -NoVenv and install by hand." }
}

# ----------------------------------------------------------------- 11. summary
Write-Host ''
Write-Info 'Done.'
Write-Host "  Release  : $relTag"
Write-Host "  Flavor   : $flavor  (official binary release$(if ($assetNames) { ": $($assetNames -join ', ')" }))"
Write-Host "  Path     : $Exe"
Write-Host "  Version  : $verLine"
Write-Host "  Record   : $InstallJson"
if ($venvPy) { Write-Host "  Python   : $venvPy  ($reqName)" } else { Write-Host '  Python   : not set up (-NoVenv)' }
switch ($FrozenState) {
    'match'     { Write-Host '  Inputs   : frozen corpora + datasets match their committed bytes' }
    'rewritten' { Write-Host '  Inputs   : REWRITTEN -- see the warning above; do not publish perplexity from this clone' }
    default     { Write-Host '  Inputs   : NOT VERIFIED (no git metadata) -- check the corpora bytes by hand before publishing perplexity' }
}
Write-Host ''
Write-Host "  Every number this build produces is a '$flavor' number. Copy flavor, tag"
Write-Host '  and driver from INSTALL.json into results\<slug>\campaign.md and into the'
Write-Host "  report's conditions block -- rule 3; and rule 30's 'never compare across"
Write-Host "  sweeps' starts with never comparing across backends."
