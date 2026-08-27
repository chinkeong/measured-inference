# Thin wrapper: the vision measurement lives in phase8b.py because Windows
# PowerShell 5.1's Invoke-RestMethod cannot post the ~261 KB body a 1440p PNG
# data-URI produces - the request never reaches the server.
$ErrorActionPreference = 'Continue'
python 'E:\AI\measured-inference\results\qwen38-27b-blind\work\phase8b.py' 2>&1 |
    ForEach-Object { Write-Host $_ }
