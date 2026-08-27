# Serialize the GPU: 3c (acceptance verify) -> 7+10 (effort + power) -> 8 (vision).
$ErrorActionPreference = 'Continue'
$w = 'E:\AI\measured-inference\results\qwen38-27b-blind\work'
foreach ($p in @('phase4b.ps1','phase4c.ps1','phase3c.ps1','phase7.ps1','phase8.ps1','power-integrate.ps1')) {
    Write-Host ("===== CHAIN START {0} {1} =====" -f $p, (Get-Date -Format 'HH:mm:ss'))
    & powershell.exe -NoProfile -ExecutionPolicy Bypass -File (Join-Path $w $p) 2>&1 | ForEach-Object { Write-Host $_ }
    Write-Host ("===== CHAIN END {0} {1} =====" -f $p, (Get-Date -Format 'HH:mm:ss'))
}
Write-Host 'CHAIN-B DONE'

