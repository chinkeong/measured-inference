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
    [switch]$OpenVINO,     # Intel CPU / iGPU / Arc / NPU: OpenVINO runtime + the win-openvino asset
    [ValidateSet('CPU', 'GPU', 'NPU', 'GPU.0', 'GPU.1')]
    [string]$OpenVINODevice = 'CPU',
    [string]$OpenVINODir,          # install prefix for the runtime (default <repo>\bin\openvino)
    [switch]$SkipOpenVINORuntime,  # a runtime is already installed; -OpenVINODir says where
    [switch]$CheckNPU,     # check the NPU prerequisites and exit; installs nothing
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

# ---- OpenVINO. MEASURED 2026-08-29 by ranged HTTP reads against ---------------------------------
# storage.openvinotoolkit.org and the GitHub releases API. The llama.cpp asset carries the
# OpenVINO version in its NAME, so the pattern is built from $OvVersion: a runtime/binary
# version mismatch is an ABI mismatch and the coupling has to be visible, not assumed.
# The POSIX twin (scripts/setup.sh) installs the Linux tarball and can also build from
# source; this side takes the published win-openvino zip only.
$OvVersion   = '2026.3.1'
$OvBuild     = '2026.3.1.22476.56d9685302d'   # what ov::get_openvino_version() reports
$OvBase      = 'https://storage.openvinotoolkit.org/repositories/openvino/packages'
# Patch releases live in their OWN directory: .../packages/2026.3.1/windows/, not 2026.3/.
# A wrong prefix answers 200 with an HTML page rather than 404, so it downloads a web page
# named .zip. Verified both ways 2026-08-29.
$OvWinZip    = "openvino_toolkit_windows_${OvBuild}_x86_64.zip"
$OvWinSha256 = '1F94CD7DD2F3B54FE8F0D3F7F77FE0C7D5AC317AAA65AB352D6CBB0459A978B1'  # Get-FileHash is uppercase
$PatOpenVino = "^llama-b\d+-bin-win-openvino-$([regex]::Escape($OvVersion))-x64\.zip$"
$NpuDriverTag = 'v1.35.0'   # intel/linux-npu-driver; Linux only, recorded here for the message
# ------------------------------------------------------------------------------------------------
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
  -OpenVINO      Intel CPU / iGPU / Arc / NPU: install the pinned OpenVINO
                 RUNTIME zip, then take the prebuilt win-openvino llama.cpp asset
  -OpenVINODevice D      CPU | GPU | NPU | GPU.0 | GPU.1 (default CPU). Recorded,
                 and exported as GGML_OPENVINO_DEVICE by openvino-env.ps1
  -OpenVINODir P install prefix for the runtime (default <repo>\bin\openvino,
                 which needs no administrator)
  -SkipOpenVINORuntime   a runtime is already installed; -OpenVINODir says where
  -CheckNPU      report the NPU silicon and exit. Installs nothing, downloads
                 nothing. Exit 7 if this part cannot run the NPU path
  -Help          this text

Environment:
  MEASURED_INFERENCE_ALLOW_VULKAN=1  same as -AllowVulkan
  MEASURED_INFERENCE_ALLOW_CRLF=1    proceed even if a frozen input no longer
                                     matches its committed bytes (CRLF rewriting)
  MEASURED_INFERENCE_DRY_RUN=1       same as -DryRun (the gpu_lock convention)

On an NVIDIA GPU, any backend other than CUDA changes every throughput number for
a reason unrelated to the model, so setup EXITS NON-ZERO rather than installing
one quietly. POSIX twin: scripts/setup.sh (same INSTALL.json, same checks).

OpenVINO REQUANTISES the file before it runs it, on every device, and says
nothing. On NPU every quantized tensor other than token_embd and output becomes
Q4_0_128 whatever the file held, so a quant ladder there compares identical
weights. -OpenVINO records this in INSTALL.json; read it before designing a
sweep (rule 3, rule 30).
'@
}
if ($Help) { Show-Usage; exit 0 }

if ($env:MEASURED_INFERENCE_ALLOW_VULKAN -eq '1') { $AllowVulkan = $true }
if ($env:MEASURED_INFERENCE_DRY_RUN -eq '1')      { $DryRun = $true }
$AllowCrlf = ($env:MEASURED_INFERENCE_ALLOW_CRLF -eq '1')
if ($Tag -and $Tag -notmatch $TagRegex) { throw "-Tag '$Tag' does not look like a llama.cpp binary release (bNNNNN)." }
if ($DryRun) { Write-Info 'DRY RUN: nothing is downloaded, written or installed.' }
if (-not $OpenVINODir) { $OpenVINODir = Join-Path $RepoRoot 'bin\openvino' }
$OvRoot   = Join-Path $OpenVINODir "openvino_$OvVersion"
$OvLibDir = $null

# ------------------------------- 0b. Intel silicon: which parts run the NPU
# The Arrow Lake NPU SIGSEGVs inside libopenvino_intel_npu_plugin.so -- confirmed
# by an Intel engineer on 2026-07-21 and still open -- while Lunar Lake and
# Panther Lake work. That is a property of the plugin, so it applies here as well
# as on Linux. The classification defaults to CAUTION: only an affirmative Lunar
# Lake or Panther Lake match clears the NPU, because the expensive mistake is a
# false all-clear on an Arrow Lake, not a spurious warning on an unknown part.
function Get-IntelSilicon {
    $name = ''
    try { $name = (Get-CimInstance Win32_Processor -ErrorAction Stop | Select-Object -First 1).Name } catch { $name = '' }
    $name = ($name -replace '\s+', ' ').Trim()
    if (-not $name)          { return @{ gen = 'unknown';   name = '';    why = 'Win32_Processor did not answer' } }
    if ($name -notmatch 'Intel') { return @{ gen = 'non-intel'; name = $name; why = "the processor name is not an Intel part: $name" } }
    # Classify on the MARKETING model number, the identity Intel publishes and a
    # reader can check against the sticker.
    # X? because Panther Lake brands a tier as "Core Ultra X7 358H" alongside
    # "Core Ultra 7 355H"; without it an X-tier part reads as pre-Ultra silicon,
    # and this script would tell a Panther Lake owner they have no NPU.
    if ($name -notmatch 'Ultra\s+X?\d+\s+(\d{3}[A-Za-z]*)') {
        return @{ gen = 'pre-ultra'; name = $name; why = "an Intel part with no 'Core Ultra NNN' model number carries no NPU: $name" }
    }
    $num = $Matches[1]
    $suffix = ($num -replace '\d', '').ToUpper()
    switch -Regex ($num) {
        '^3'    { return @{ gen = 'panther-lake'; name = $name; why = "Core Ultra series 3 ($num) is Panther Lake" } }
        '^2'    {
            if ($suffix -eq 'V') { return @{ gen = 'lunar-lake'; name = $name; why = "Core Ultra series 2 with a V suffix ($num) is Lunar Lake" } }
            return @{ gen = 'arrow-lake'; name = $name; why = "Core Ultra series 2 without a V suffix ($num) is Arrow Lake" }
        }
        '^1'    { return @{ gen = 'meteor-lake'; name = $name; why = "Core Ultra series 1 ($num) is Meteor Lake" } }
        default { return @{ gen = 'unknown'; name = $name; why = "model number '$num' matches no Core Ultra series this script knows" } }
    }
}
$Silicon = @{ gen = 'unknown'; name = ''; why = 'not looked at' }
$NpuStatus = $null
$NpuFindings = @()
function Test-NpuSilicon {
    $script:Silicon = Get-IntelSilicon
    Write-Host ''
    Write-Info '--- Intel NPU silicon (checked, never installed) ---'
    Write-Info "CPU        : $($Silicon.name)"
    Write-Info "Silicon    : $($Silicon.gen) -- $($Silicon.why)"
    switch ($Silicon.gen) {
        'arrow-lake' {
            $script:NpuFindings += 'Arrow Lake: the NPU SIGSEGVs inside libopenvino_intel_npu_plugin.so (Intel engineer, 2026-07-21, still open)'
            Write-Warn 'ARROW LAKE NPU IS BROKEN. It is not a configuration problem and there is no flag for it.'
            Write-Warn 'Lunar Lake and Panther Lake work. Run the Intel arms on GPU or CPU here: .\scripts\setup.ps1 -OpenVINO -OpenVINODevice GPU'
        }
        'lunar-lake'   { Write-Info 'NPU silicon: llama.cpp validates the OpenVINO NPU path on Core Ultra 5 238V (Lunar Lake).' }
        'panther-lake' { Write-Info 'NPU silicon: Panther Lake works.' }
        'meteor-lake'  {
            $script:NpuFindings += 'Meteor Lake NPU: present, but the OpenVINO NPU path is validated on Lunar Lake, not here'
            Write-Warn "Meteor Lake has an NPU, but llama.cpp's validated OpenVINO NPU box is Lunar Lake. Treat any NPU number from this part as unvalidated and say so (rule 1)."
        }
        default {
            if ($Silicon.gen -eq 'pre-ultra' -or $Silicon.gen -eq 'non-intel') {
                $script:NpuFindings += "no NPU silicon: $($Silicon.why)"
                Write-Warn 'This part has no NPU. Use -OpenVINODevice CPU or GPU.'
            } else {
                $script:NpuFindings += 'silicon generation unidentified, so the Arrow Lake exclusion cannot be checked'
                Write-Warn 'Could not identify the silicon generation, so this script cannot tell you whether the Arrow Lake segfault applies. Check the model number by hand before spending an hour.'
            }
        }
    }
    Write-Info 'Driver     : the Windows NPU driver comes from Windows Update / Intel, not from this script.'
    Write-Info "             The Linux driver this repo pins is intel/linux-npu-driver $NpuDriverTag (Ubuntu 24.04 only)."
    if ($NpuFindings.Count -eq 0) { $script:NpuStatus = 'ok' } else { $script:NpuStatus = 'blocked' }
    Write-Host ''
}
if ($CheckNPU) {
    Test-NpuSilicon
    Write-Host @'
[setup] Three NPU run-time conditions that no check reports and that change your numbers:
[setup]   - llama-server on NPU needs an EXPLICIT -c. Without one it takes the model's
[setup]     training context, which is usually far larger than you meant and changes
[setup]     both the fit and the speed (rule 3; rule 16).
[setup]   - llama-server on NPU cannot handle parallel sequences: --parallel 1 only.
[setup]   - Every quantized tensor other than token_embd and output is rewritten to
[setup]     Q4_0_128 on NPU, whatever the file holds. A quant ladder there compares
[setup]     arms that are the same weights (rule 30). Use CPU or GPU for a ladder.
'@
    if ($NpuStatus -eq 'ok') { exit 0 }
    exit 7
}

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
# DGX Spark. Two independent signals, either one enough (rule 4): the board name
# and compute capability 12.1, which no other shipping part reports. The Spark
# ships Ubuntu, so this side only has to recognise it and hand over.
$computeCap = $null
$gb10 = $false
if ($hasSmi) {
    $cc = (& nvidia-smi --query-gpu=compute_cap --format=csv,noheader | Select-Object -First 1)
    if ($cc) { $computeCap = $cc.Trim() }
}
if ($gpuName -match 'GB10|DGX Spark') { $gb10 = $true }
elseif ($computeCap -eq '12.1')       { $gb10 = $true }
if ($gb10) {
    Write-Warn 'DGX Spark GB10 detected. Its measuring path is the Linux source build, scripts/setup.sh --cuda --cuda-arch 121a-real -- 120, 120f and native all build and lose MMVQ_PARAMETERS_GB10. This script installs Windows binaries and has no such path.'
    Write-Warn 'GB10 also has UNIFIED memory and no discrete board, so nvidia-smi VRAM sampling and the board_total_mib - reserve arithmetic both fail SILENTLY on it (rule 13). See reference/platform-notes.md.'
}
# -OpenVINO replaces the flavor rather than extending a candidate list: there is
# no "openvino, else cpu" fallback, because a CPU build installed under an
# openvino record is the silent backend substitution section 3 refuses.
if ($OpenVINO) {
    if ($arch -ne 'x86_64') { throw "-OpenVINO on '$arch': the OpenVINO runtime and the llama.cpp win-openvino asset are both x86_64-only at $OvVersion (checked 2026-08-29)." }
    $flavor = 'openvino'
}
Write-Info "os=Windows arch=$arch gpu=$gpu$(if ($gpuName) { " ($gpuName$(if ($driver) { ", driver $driver" }))" })$(if ($computeCap) { " compute_cap=$computeCap" })"
Write-Info "backend flavor: $flavor"
if ($OpenVINO) {
    Write-Info "OpenVINO backend requested: runtime $OvVersion ($OvBuild), device $OpenVINODevice, prefix $OpenVINODir"
    # Said once, before anything is downloaded, because it governs sweep DESIGN
    # and not just reporting: by the time a ladder has run, the money is spent.
    Write-Warn 'OpenVINO REQUANTISES the file before it runs it, on every device, and logs nothing (ggml-openvino-extra.cpp:252-273; the four reporting lines are commented out at ggml-openvino.cpp:332-346, read 2026-08-29).'
    Write-Warn '  token_embd -> F16 on NPU from Q6_K, else Q8_0_C. output -> Q8_0_C. Always, any device.'
    Write-Warn '  Q6_K and Q5_K -> Q8_0_C off NPU. Q8_0_C is CHANNEL-WISE (one scale per row), so that is more bits at COARSER scale granularity -- not an upgrade.'
    if ($OpenVINODevice -eq 'NPU') {
        Write-Warn '  ON NPU every other quantized tensor becomes Q4_0_128 whatever the file held -- Q8_0, Q5_K, Q6_K, Q4_K_M, Q4_1 all collapse to one representation, and even Q4_0 is re-blocked from 32 to 128 weights per block.'
        Write-Warn '  A QUANT LADDER ON THIS DEVICE IS DEGENERATE: the arms are the same weights (rule 30). Run the ladder on CPU or GPU, or drop it and say why.'
        Test-NpuSilicon
        if ($NpuStatus -ne 'ok') {
            throw "-OpenVINODevice NPU, but this silicon cannot run it (see above). Pick a device that works here: -OpenVINODevice GPU (or CPU)."
        }
    }
}

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

# -------------------------------------- 3b. the OpenVINO runtime archive
# The RUNTIME is what -OpenVINO installs; the llama.cpp binaries are the small
# half. The default prefix is inside the repo, not Program Files, because this
# script promises no administrator -- pass -OpenVINODir to put it elsewhere.
$OvRuntimeSource = $null
$OvSha256 = $null
$OvShaProvenance = $null
function Resolve-OvLibDir {
    # The documented layout is runtime\bin\intel64\Release, but that is a claim
    # about an archive this script cannot inspect before downloading it. Find the
    # directory that actually holds openvino.dll instead: a hard-coded path that
    # drifted would fail at the first server launch, hours later, not here.
    param([string]$Root)
    if (-not $Root -or -not (Test-Path -LiteralPath $Root)) { return $null }
    $hit = Get-ChildItem -LiteralPath $Root -Recurse -Filter 'openvino.dll' -ErrorAction SilentlyContinue |
           Select-Object -First 1
    if ($hit) { return $hit.DirectoryName }
    return $null
}
function Install-OpenVINORuntime {
    if ($SkipOpenVINORuntime) {
        # CITED, not measured: the operator says a runtime is there, and the only
        # thing checked is that its libraries can be found.
        $script:OvLibDir = Resolve-OvLibDir -Root $OvRoot
        if (-not $OvLibDir) { throw "-SkipOpenVINORuntime, but no openvino.dll was found anywhere under $OvRoot. Point -OpenVINODir at the PREFIX that holds openvino_$OvVersion\, not at the runtime directory itself." }
        $script:OvRuntimeSource = 'pre-existing, -SkipOpenVINORuntime'
        Write-Info "OpenVINO runtime: using the existing $OvRoot, libraries at $OvLibDir (nothing else about it is verified)."
        return
    }
    if (-not $Force) {
        $existing = Resolve-OvLibDir -Root $OvRoot
        if ($existing) {
            $script:OvLibDir = $existing
            $script:OvRuntimeSource = "already present at $OvRoot"
            Write-Info "OpenVINO runtime $OvVersion already at $OvRoot -- keeping it (-Force to reinstall)."
            return
        }
    }
    $url = "$OvBase/$OvVersion/windows/$OvWinZip"
    New-Item -ItemType Directory -Force -Path $DlDir | Out-Null
    $zip = Join-Path $DlDir $OvWinZip
    Write-Info "Downloading the OpenVINO $OvVersion runtime (~198 MB)..."
    Write-Info "  $url"
    $curl = Get-Command curl.exe -ErrorAction SilentlyContinue
    if ($curl) {
        & $curl.Source -fL -C - --retry 3 --retry-delay 2 -o $zip $url
        if ($LASTEXITCODE -ne 0) { & $curl.Source -fL --retry 3 -o $zip $url }
        if ($LASTEXITCODE -ne 0) { throw "Download failed: $url`nNote the directory: patch releases live under packages/$OvVersion/, not packages/$($OvVersion -replace '\.\d+$',''). A wrong prefix answers 200 with an HTML page, so check what landed before blaming the network." }
    } else {
        Invoke-WebRequest -Uri $url -OutFile $zip -Headers @{ 'User-Agent' = 'measured-inference-setup' }
    }
    $got = (Get-FileHash -LiteralPath $zip -Algorithm SHA256).Hash
    if ($got -ne $OvWinSha256) {
        throw "OpenVINO runtime checksum mismatch.`n       expected $OvWinSha256   (read from storage.openvinotoolkit.org 2026-08-29 and pinned in this script)`n       got      $got`nEither the download is truncated or the published artefact changed. Delete $zip and retry; if it persists, the pinned constant needs re-reading, and that is a finding, not a nuisance."
    }
    $script:OvSha256 = $got
    $script:OvShaProvenance = 'measured, Get-FileHash of the downloaded file, matches the constant pinned 2026-08-29'

    $staging = Join-Path $DlDir "ov-staging-$PID"
    if (Test-Path -LiteralPath $staging) { Remove-Item -LiteralPath $staging -Recurse -Force -Confirm:$false }
    New-Item -ItemType Directory -Force -Path $staging | Out-Null
    Write-Info "Extracting to $OvRoot ..."
    Expand-Archive -Path $zip -DestinationPath $staging -Force
    # The archive's top-level directory carries the full build string; taking
    # "whatever single directory landed" avoids depending on that name.
    $top = @(Get-ChildItem -LiteralPath $staging -Directory)
    if ($top.Count -eq 1) { $payload = $top[0].FullName } else { $payload = $staging }
    if (-not (Resolve-OvLibDir -Root $payload)) { throw "the extracted archive contains no openvino.dll -- this is not the OpenVINO runtime, or its layout changed. Nothing has been installed." }
    if (Test-Path -LiteralPath $OvRoot) { Remove-Item -LiteralPath $OvRoot -Recurse -Force -Confirm:$false }
    New-Item -ItemType Directory -Force -Path $OpenVINODir | Out-Null
    Move-Item -LiteralPath $payload -Destination $OvRoot
    Remove-Item -LiteralPath $staging -Recurse -Force -Confirm:$false -ErrorAction SilentlyContinue
    Remove-Item -LiteralPath $zip -Force -Confirm:$false
    # A JUNCTION, not a symbolic link: junctions need no administrator and no
    # developer mode, which is the whole point of the versioned directory --
    # swapping the active version stays one command.
    $active = Join-Path $OpenVINODir 'openvino'
    try {
        if (Test-Path -LiteralPath $active) { Remove-Item -LiteralPath $active -Recurse -Force -Confirm:$false }
        New-Item -ItemType Junction -Path $active -Target $OvRoot -ErrorAction Stop | Out-Null
    } catch {
        Write-Warn "could not create the $active junction; the versioned path still works."
    }
    $script:OvLibDir = Resolve-OvLibDir -Root $OvRoot
    $script:OvRuntimeSource = $url
    Write-Info "OpenVINO runtime $OvVersion installed: $OvRoot"
    Write-Info "  libraries: $OvLibDir"
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
    if ($OpenVINO) {
        if ($SkipOpenVINORuntime) {
            Write-Info "runtime : skip (-SkipOpenVINORuntime); expects openvino.dll somewhere under $OvRoot"
        } else {
            Write-Info "runtime : OpenVINO $OvVersion -> $OvRoot, active via a junction at $OpenVINODir\openvino"
            Write-Info "          $OvBase/$OvVersion/windows/$OvWinZip"
            Write-Info "          sha256 checked against the constant pinned in this script"
        }
        Write-Info "device  : GGML_OPENVINO_DEVICE=$OpenVINODevice (written into $Dest\openvino-env.ps1)"
        Write-Info 'note    : the backend requantises on every device and logs nothing; on NPU every'
        Write-Info '          quantized tensor but token_embd/output becomes Q4_0_128, so a quant'
        Write-Info '          ladder there is degenerate (rule 30). Recorded in INSTALL.json.'
    }
    if ($skipInstall) {
        Write-Info "install : skip ($relTag / $flavor already present); INSTALL.json rewritten with the recorded install provenance carried forward"
    } else {
        $wantedPats = if ($flavor -eq 'cuda') { "$PatCuda + $PatCudart" } elseif ($flavor -eq 'openvino') { $PatOpenVino } elseif ($flavor -eq 'vulkan') { $PatVulkan } else { $PatCpu }
        Write-Info "install : binary release -> $Dest"
        Write-Info "          assets matching: $wantedPats"
    }
    Write-Info "record  : $InstallJson  (tag, flavor=$flavor, arch=$arch, os, assets, urls, installed_utc,"
    Write-Info '          built_from_source, cuda_arch + cuda_arch_source + cuda_arch_override, gb10,'
    Write-Info '          openvino_version/build/root/device/install_path/runtime_sha256, openvino_requantises,'
    Write-Info '          openvino_npu_quant_ladder_degenerate, multimodal_supported, cpu_gen, npu_status)'
    if ($NoVenv) { Write-Info 'python  : skipped (-NoVenv)' }
    else { Write-Info "python  : $RepoRoot\.venv + $(if ($Publish) { 'requirements.txt' } else { 'requirements-min.txt' })" }
    Write-Info '--- end of plan; nothing was changed ---'
    exit 0
}

# ------------------------------------------------------- 7. download + extract
$assetNames = @(); $assetUrls = @()
# The runtime is installed OUTSIDE the idempotency skip. Skipping the llama.cpp
# install says the binaries are already here; it says nothing about the runtime
# they link against, and a missing runtime is what an "already installed" server
# fails on at its first launch.
if ($OpenVINO) { Install-OpenVINORuntime }
if (-not $skipInstall) {
    if (-not $rel) {
        $rel = Invoke-RestMethod -Uri "https://api.github.com/repos/ggml-org/llama.cpp/releases/tags/$relTag" -Headers $headers
    }
    if ($flavor -eq 'cuda')         { $wanted = @($PatCuda, $PatCudart) }
    elseif ($flavor -eq 'openvino') { $wanted = @($PatOpenVino) }
    elseif ($flavor -eq 'vulkan')   { $wanted = @($PatVulkan) }
    else                            { $wanted = @($PatCpu) }
    $assets = @()
    foreach ($pat in $wanted) {
        $a = $rel.assets | Where-Object { $_.name -match $pat } | Select-Object -First 1
        if (-not $a) {
            if ($flavor -eq 'openvino') {
                throw "No asset in $relTag matches '$pat'. The win-openvino zip is published per release and carries the OpenVINO version in its name, so either this tag has none or the runtime version moved. Pin a release that has one (-Tag bNNNNN; verified present on b10675..b10679) rather than installing a different backend under an openvino record."
            }
            throw "No asset in $relTag matches pattern '$pat' -- release naming drifted; update the patterns at the top of this script."
        }
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
# The OpenVINO runtime deliberately stays in its swappable versioned prefix, so
# its DLL directory has to be on PATH before llama-server can even answer
# --version. Prepended for this process only; openvino-env.ps1 below is what a
# launcher dot-sources.
$needsPath = $false
if ($flavor -eq 'openvino') {
    if (-not $OvLibDir) { $OvLibDir = Resolve-OvLibDir -Root $OvRoot }
    if (-not $OvLibDir) { throw "the OpenVINO backend is installed but no openvino.dll was found under $OvRoot -- llama-server cannot start without it." }
    $env:PATH = "$OvLibDir;$env:PATH"
    $needsPath = $true
}
$verOut = & cmd /c "`"$Exe`" --version 2>&1"
if ($LASTEXITCODE -ne 0) { throw "llama-server.exe --version failed (exit $LASTEXITCODE): $verOut" }
$verLine = (($verOut | Select-Object -First 2) -join ' | ')
Set-Content -Path $VersionFile -Value $relTag -Encoding ascii

# One file to dot-source, so the DLL path and the device do not have to be
# remembered separately at every launch, and so the device that ran is written
# down somewhere a later reader can find it (rule 28).
if ($flavor -eq 'openvino') {
    $envPs1 = Join-Path $Dest 'openvino-env.ps1'
    $envText = @"
# written by scripts\setup.ps1 -- dot-source before launching llama-server
# OpenVINO $OvVersion ($OvBuild), device $OpenVINODevice
`$env:PATH = '$OvLibDir' + ';' + `$env:PATH
`$env:GGML_OPENVINO_DEVICE = '$OpenVINODevice'
# GGML_OPENVINO_STATEFUL_EXECUTION=1 is experimental, faster on CPU/GPU, and
# limits llama-server to ONE chat session -- do not set it under a sweep that
# uses parallel slots, and record it as an arm condition if you do set it.
# GGML_OPENVINO_DUMP_IR=1 dumps the graph that actually ran: the only way to
# prove which tensor types executed, since the type-change log lines are
# commented out at ggml-openvino.cpp:332-346.
"@
    [IO.File]::WriteAllText($envPs1, ($envText -replace "`r`n", "`n") + "`n", (New-Object Text.UTF8Encoding($false)))
    Write-Info "Wrote $envPs1 (PATH + GGML_OPENVINO_DEVICE=$OpenVINODevice)."
}

# ------------------------------------------- 9. INSTALL.json: what this IS
# $flavor used to be computed and thrown away, so no report could state whether
# its numbers were CUDA, Vulkan or CPU -- rule 3's strongest condition, unrecorded.
# Written the moment it is known (rule 28), in the same schema setup.sh writes.
$tools = @($WantedTools | Where-Object { Test-Path (Join-Path $Dest $_) })
$osDesc = "$((Get-CimInstance Win32_OperatingSystem).Caption) ($([Environment]::OSVersion.Version.ToString()))"

# ---- what the INSTALL ACT established, carried forward across a skip ----------
# A re-run that installs nothing must not rewrite the record as though it had:
# before this, an idempotent second run replaced the recorded assets and urls
# with empty lists, deleting the only statement of which binaries produced the
# numbers (rule 3). The same fix is in the POSIX twin.
$prev = $null
if ($skipInstall -and (Test-Path $InstallJson)) {
    try { $prev = Get-Content $InstallJson -Raw | ConvertFrom-Json } catch { $prev = $null }
}
function Keep {
    # On a skip the recorded value wins, when the record actually has one.
    param([string]$Key, $Fresh)
    if ($prev -and ($prev.PSObject.Properties.Name -contains $Key) -and $null -ne $prev.$Key) { return $prev.$Key }
    return $Fresh
}
$ovVersionRec  = $null; $ovBuildRec = $null; $ovRootRec = $null; $ovDeviceRec = $null
$ovPathRec     = $null; $ovRequant  = $null; $ovLadder  = $null
$multimodal    = $true
if ($flavor -eq 'openvino') {
    $ovVersionRec = $OvVersion
    $ovBuildRec   = $OvBuild
    $ovRootRec    = $OvRoot
    $ovDeviceRec  = $OpenVINODevice
    $ovPathRec    = 'prebuilt-asset'   # Windows has no source path in this script
    # Not a warning flag: a fact about what ran, so a report can state it and a
    # planner can refuse a ladder without re-deriving it from the source tree.
    $ovRequant    = $true
    $ovLadder     = ($OpenVINODevice -eq 'NPU')
    $multimodal   = $false             # ggml-openvino is text-only; multimodal is incomplete
}
$cpuGenRec = $null
if ($Silicon.gen -ne 'unknown') { $cpuGenRec = $Silicon.gen }
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
    assets                     = @(Keep 'assets' $assetNames)
    urls                       = @(Keep 'urls'   $assetUrls)
    installed_utc              = (Get-Date).ToUniversalTime().ToString('yyyy-MM-ddTHH:mm:ssZ')
    built_from_source          = $false      # Windows has official CUDA binaries; setup.sh is the source-build path
    # cuda_arch is null here and NOT a placeholder: it is the source build's
    # flag, and this script never runs one. The GB10 path is scripts/setup.sh.
    cuda_arch                  = $null
    cuda_arch_source           = $null
    cuda_arch_override         = $false
    gb10                       = $gb10
    compute_cap                = $computeCap
    openvino_version                     = Keep 'openvino_version' $ovVersionRec
    openvino_build                       = Keep 'openvino_build'   $ovBuildRec
    openvino_root                        = Keep 'openvino_root'    $ovRootRec
    openvino_device                      = $ovDeviceRec            # re-measured: openvino-env.ps1 is rewritten every run
    openvino_install_path                = Keep 'openvino_install_path' $ovPathRec
    openvino_runtime_source              = Keep 'openvino_runtime_source' $OvRuntimeSource
    openvino_runtime_sha256              = Keep 'openvino_runtime_sha256' $OvSha256
    openvino_runtime_sha256_provenance   = Keep 'openvino_runtime_sha256_provenance' $OvShaProvenance
    openvino_requantises                 = Keep 'openvino_requantises' $ovRequant
    openvino_npu_quant_ladder_degenerate = Keep 'openvino_npu_quant_ladder_degenerate' $ovLadder
    multimodal_supported                 = Keep 'multimodal_supported' $multimodal
    cpu_gen                    = $cpuGenRec
    npu_status                 = $NpuStatus
    npu_findings               = @($NpuFindings)
    gpu                        = $gpu
    gpu_name                   = $gpuName
    driver_version             = $driver
    server_version             = $verLine
    source_commit              = $null
    build_seconds              = $null
    tools                      = @(Keep 'tools' $tools)
    # On Windows the loader path is PATH, not LD_LIBRARY_PATH; the field keeps
    # its POSIX name so both scripts write one schema, and carries the DLL
    # directory the OpenVINO build needs.
    needs_ld_library_path      = $needsPath
    ld_library_path            = $OvLibDir
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
if ($flavor -eq 'openvino') {
    Write-Host "  OpenVINO : $OvVersion ($OvBuild) at $OvRoot, device $OpenVINODevice"
    Write-Host "  Env      : dot-source $Dest\openvino-env.ps1 before any launch"
}
if ($gb10) { Write-Host '  Board    : DGX Spark GB10 -- unified memory, no discrete board' }
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
if ($flavor -eq 'openvino') {
    Write-Host @'

  AND THE FILE ON DISK IS NOT THE WEIGHTS THAT RAN. OpenVINO requantises before
  it executes, on every device, and the log lines that would say so are
  commented out. token_embd and output are rewritten always; Q6_K and Q5_K
  become Q8_0_C off NPU -- more bits at a COARSER scale granularity, one scale
  per row, so do not write it up as an upgrade. INSTALL.json now carries
  openvino_requantises: true. Two consequences you cannot design around:
    - A quant file name is not a description of the arm. State the requantisation
      beside every OpenVINO number (rule 3), and prove what ran with
      GGML_OPENVINO_DUMP_IR=1 rather than from the filename.
    - On NPU a quant ladder compares identical weights. Run ladders on CPU or GPU.
  Multimodal is incomplete in this backend: INSTALL.json records
  multimodal_supported: false, so a vision stage here measures nothing (rule 2).
  Capture 'OpenVINO: using device' from the server log on the first launch -- it
  prints the RESOLVED device after availability fallback, so it is the one line
  that catches a silent NPU-to-CPU downgrade.

  scripts/detect-machine.py reads 'openvino' out of INSTALL.json as the MEASURED
  backend, so machine.json and this record agree without a -backend flag. Check
  that they do agree before either reaches a report.
'@
}
