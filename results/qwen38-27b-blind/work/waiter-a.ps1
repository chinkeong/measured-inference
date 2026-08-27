$log = 'E:\AI\measured-inference\results\qwen38-27b-blind\data\phase3-run.log'
for ($i=0; $i -lt 600; $i++) { if ((Get-Content $log -ErrorAction SilentlyContinue) -match 'PHASE3 DONE') { break }; Start-Sleep -Seconds 3 }
& powershell.exe -NoProfile -ExecutionPolicy Bypass -File 'E:\AI\measured-inference\results\qwen38-27b-blind\work\chain-a.ps1'