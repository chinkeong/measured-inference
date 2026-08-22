#Requires -Version 5.1
# Bootstrap a self-contained llama.cpp into <repo>\bin\llama.cpp\ -- no admin, nothing outside the repo tree.
# Usage: .\setup.ps1 [-Force]
param([switch]$Force)
$ErrorActionPreference = 'Stop'

# ---- Asset name patterns (regex, matched against release asset names) --------------------------
# Verified against release b10582 (2026-08-22). Names drift between releases; fix here if selection fails.
# CUDA 12.4 chosen over the also-published 13.3 for wider driver compatibility (fine for RTX 3090).
$PatCuda   = '^llama-b\d+-bin-win-cuda-12\.4-x64\.zip$'    # Windows x64 CUDA build
$PatCudart = '^cudart-llama-bin-win-cuda-12\.4-x64\.zip$'  # CUDA runtime DLLs -- REQUIRED companion, same CUDA ver
$PatVulkan = '^llama-b\d+-bin-win-vulkan-x64\.zip$'        # Intel/AMD GPUs
$PatCpu    = '^llama-b\d+-bin-win-cpu-x64\.zip$'           # no-GPU fallback
$TagRegex  = '^b\d+$'  # binary releases are tagged bNNNNN; /releases/latest points elsewhere (v0.2.0 nightly tracker) -- do not use it
# ------------------------------------------------------------------------------------------------

$RepoRoot    = Split-Path -Parent $PSScriptRoot
$Dest        = Join-Path $RepoRoot 'bin\llama.cpp'
$DlDir       = Join-Path $Dest '.downloads'
$VersionFile = Join-Path $Dest 'VERSION.txt'
$Exe         = Join-Path $Dest 'llama-server.exe'

# 1. Detect GPU vendor
$flavor = 'cpu'
if (Get-Command nvidia-smi -ErrorAction SilentlyContinue) { $flavor = 'cuda' }
else {
    try { $gpuNames = (Get-CimInstance Win32_VideoController -ErrorAction Stop).Name -join '; ' } catch { $gpuNames = '' }
    if ($gpuNames -match 'Intel|AMD|Radeon|Arc') { $flavor = 'vulkan' }   # Intel -> prefer Vulkan build
}
Write-Host "[setup] GPU flavor: $flavor"

# 2. Find the newest bNNNNN release via the GitHub API
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
$headers = @{ 'User-Agent' = 'measured-inference-setup'; 'Accept' = 'application/vnd.github+json' }
$releases = Invoke-RestMethod -Uri 'https://api.github.com/repos/ggml-org/llama.cpp/releases?per_page=10' -Headers $headers
$rel = $releases | Where-Object { $_.tag_name -match $TagRegex -and $_.assets.Count -gt 0 } | Select-Object -First 1
if (-not $rel) { throw "No bNNNNN release with assets found in the 10 most recent releases -- check `$TagRegex." }
$tag = $rel.tag_name
Write-Host "[setup] Latest binary release: $tag"

# 3. Idempotency: skip if this version is already installed and functional
if (-not $Force -and (Test-Path $VersionFile) -and (Test-Path $Exe)) {
    $have = (Get-Content $VersionFile -TotalCount 1).Trim()
    if ($have -eq $tag) {
        Write-Host "[setup] $tag already installed at $Dest -- nothing to do (use -Force to redownload)."
        exit 0
    }
    Write-Host "[setup] Installed version '$have' != latest '$tag' -- updating."
}

# 4. Pick assets by pattern
if ($flavor -eq 'cuda')       { $wanted = @($PatCuda, $PatCudart) }
elseif ($flavor -eq 'vulkan') { $wanted = @($PatVulkan) }
else                          { $wanted = @($PatCpu) }
$assets = @()
foreach ($pat in $wanted) {
    $a = $rel.assets | Where-Object { $_.name -match $pat } | Select-Object -First 1
    if (-not $a) { throw "No asset in $tag matches pattern '$pat' -- release naming drifted; update the patterns at the top of this script." }
    $assets += $a
}

# 5. Download (resumable via curl.exe, shipped with Windows 10+) and extract
New-Item -ItemType Directory -Force -Path $Dest, $DlDir | Out-Null
$curl = Get-Command curl.exe -ErrorAction SilentlyContinue
foreach ($a in $assets) {
    $zip = Join-Path $DlDir $a.name
    Write-Host "[setup] Downloading $($a.name) ($([math]::Round($a.size/1MB,1)) MB)..."
    if ($curl) {
        & $curl.Source -fL -C - --retry 3 --retry-delay 2 -o $zip $a.browser_download_url
        if ($LASTEXITCODE -ne 0) { & $curl.Source -fL --retry 3 -o $zip $a.browser_download_url }  # resume unsupported -> fresh
        if ($LASTEXITCODE -ne 0) { throw "Download failed: $($a.browser_download_url)" }
    } else {
        Invoke-WebRequest -Uri $a.browser_download_url -OutFile $zip -Headers @{ 'User-Agent' = 'measured-inference-setup' }
    }
    Write-Host "[setup] Extracting $($a.name)..."
    Expand-Archive -Path $zip -DestinationPath $Dest -Force   # win zips are flat: exes/DLLs land in $Dest
    Remove-Item $zip -Force -Confirm:$false
}

# 6. Verify llama-server.exe exists and runs
if (-not (Test-Path $Exe)) { throw "llama-server.exe not found in $Dest after extraction." }
$verOut = & cmd /c "`"$Exe`" --version 2>&1"
if ($LASTEXITCODE -ne 0) { throw "llama-server.exe --version failed (exit $LASTEXITCODE): $verOut" }
Set-Content -Path $VersionFile -Value $tag -Encoding ascii

# 7. Summary
Write-Host ""
Write-Host "[setup] Done."
Write-Host "  Release  : $tag"
Write-Host "  Flavor   : $flavor  (assets: $(($assets | ForEach-Object name) -join ', '))"
Write-Host "  Path     : $Exe"
Write-Host "  Version  : $(($verOut | Select-Object -First 2) -join ' | ')"
