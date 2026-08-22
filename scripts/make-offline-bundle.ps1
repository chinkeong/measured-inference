# make-offline-bundle.ps1 - pre-download every external dependency into one
# folder for USB transfer to an air-gapped / internet-less machine.
# Run this on a machine WITH internet; copy offline-bundle\ (plus bin\ and
# models\ if already populated) alongside the cloned repo on the target.
# Usage: .\make-offline-bundle.ps1 [-IncludeModels <hf-file-url>[,<url>...]]
param([string[]]$IncludeModels = @())
$ErrorActionPreference = 'Stop'
$root = Split-Path $PSScriptRoot -Parent
$out = Join-Path $root 'offline-bundle'
New-Item -ItemType Directory -Force $out, "$out\llama.cpp", "$out\wheels", "$out\repos", "$out\models" | Out-Null

Write-Host '[1/4] llama.cpp release builds (all platforms this repo targets)...'
$rel = Invoke-RestMethod 'https://api.github.com/repos/ggml-org/llama.cpp/releases/latest'
$rel.tag_name | Set-Content "$out\llama.cpp\RELEASE_TAG.txt"
# Patterns mirror scripts/setup.ps1 - keep in sync if asset naming drifts.
$patterns = @('*win-cuda*x64*', '*win-vulkan*x64*', '*ubuntu*vulkan*x64*', '*ubuntu*x64*', '*cudart*win*')
foreach ($p in $patterns) {
    foreach ($a in ($rel.assets | Where-Object { $_.name -like $p })) {
        $dest = Join-Path "$out\llama.cpp" $a.name
        if (-not (Test-Path $dest)) {
            Write-Host "  $($a.name) ($([math]::Round($a.size/1MB)) MB)"
            curl.exe -L --retry 5 -o $dest $a.browser_download_url --silent --show-error
        }
    }
}

Write-Host '[2/4] python wheels for the bench harness (requests, Pillow)...'
python -m pip download requests pillow -d "$out\wheels" --quiet
'python -m pip install --no-index --find-links . requests pillow' | Set-Content "$out\wheels\INSTALL.txt"

Write-Host '[3/4] git bundles for the agentic bucket (best-effort)...'
foreach ($r in @('https://github.com/datacurve-ai/deep-swe', 'https://github.com/datacurve-ai/pier')) {
    $name = ($r -split '/')[-1]
    $tmp = Join-Path $env:TEMP "mib-$name"
    try {
        if (Test-Path $tmp) { Remove-Item -Recurse -Force $tmp }
        git clone --quiet $r $tmp
        git -C $tmp bundle create "$out\repos\$name.bundle" --all
        Write-Host "  $name.bundle"
    } catch { Write-Host "  SKIPPED $name ($($_.Exception.Message))" }
}
'git clone <name>.bundle <dir>   # restores the repo offline' | Set-Content "$out\repos\INSTALL.txt"

Write-Host '[4/4] model weights (only if URLs were passed)...'
foreach ($u in $IncludeModels) {
    $name = ($u -split '/')[-1] -replace '\?.*$', ''
    Write-Host "  $name"
    curl.exe -L -C - --retry 10 -o (Join-Path "$out\models" $name) $u --silent --show-error
}

Write-Host "DONE -> $out"
Write-Host 'Target machine: clone the repo, copy offline-bundle\ next to it, then:'
Write-Host '  - unzip the matching llama.cpp asset into bin\llama.cpp\'
Write-Host '  - pip install from wheels\ per INSTALL.txt (into the repo .venv)'
Write-Host '  - git clone the .bundle files where the agentic setup expects them'
Write-Host '  - move models\* into the repo models\ folder'
Write-Host 'Datasets and corpora need nothing: they are frozen in the repo itself.'
