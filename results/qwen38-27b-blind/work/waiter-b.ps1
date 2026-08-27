$log = 'E:\AI\measured-inference\results\qwen38-27b-blind\data\chain-a.log'
for ($i=0; $i -lt 1200; $i++) { if ((Get-Content $log -ErrorAction SilentlyContinue) -match 'CHAIN-A DONE') { break }; Start-Sleep -Seconds 5 }
& powershell.exe -NoProfile -ExecutionPolicy Bypass -File 'E:\AI\measured-inference\results\qwen38-27b-blind\work\chain-b.ps1'