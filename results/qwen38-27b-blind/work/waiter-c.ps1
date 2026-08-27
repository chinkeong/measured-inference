$log = 'E:\AI\measured-inference\results\qwen38-27b-blind\data\chain-b.log'
for ($i=0; $i -lt 2400; $i++) { if ((Get-Content $log -ErrorAction SilentlyContinue) -match 'CHAIN-B DONE') { break }; Start-Sleep -Seconds 5 }
& powershell.exe -NoProfile -ExecutionPolicy Bypass -File 'E:\AI\measured-inference\results\qwen38-27b-blind\work\phase6.ps1'