# Serialize the GPU: 3b (anti-overfit confirm) -> 4 (ceilings) -> 5 (depth).
$ErrorActionPreference = 'Continue'
$w = 'E:\AI\measured-inference\results\qwen38-27b-blind\work'
foreach ($p in @('phase3b.ps1','phase4.ps1','phase5.ps1')) {
    Write-Host ("===== CHAIN START {0} {1} =====" -f $p, (Get-Date -Format 'HH:mm:ss'))
    & powershell.exe -NoProfile -ExecutionPolicy Bypass -File (Join-Path $w $p) 2>&1 | ForEach-Object { Write-Host $_ }
    Write-Host ("===== CHAIN END {0} {1} =====" -f $p, (Get-Date -Format 'HH:mm:ss'))
}
Write-Host 'CHAIN-A DONE'
