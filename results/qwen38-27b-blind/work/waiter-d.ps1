$log = 'E:\AI\measured-inference\results\qwen38-27b-blind\data\chain-c.log'
for ($i=0; $i -lt 3000; $i++) { if ((Get-Content $log -ErrorAction SilentlyContinue) -match 'PHASE6 DONE') { break }; Start-Sleep -Seconds 5 }
& powershell.exe -NoProfile -ExecutionPolicy Bypass -File 'E:\AI\measured-inference\results\qwen38-27b-blind\work\phase5b.ps1'