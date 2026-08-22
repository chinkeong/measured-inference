# Refinement around the n-max 4 / p-min 0.75 winner.
$ErrorActionPreference = 'Continue'
$env:PROBE_TEXT = 'Write a single self-contained JavaScript file implementing a red-black tree class with insert, delete, search and an in-order iterator. Code only, no explanation.'
$configs = @(
    @('-ngl','99','--spec-type','draft-mtp','--spec-draft-n-max','4','--spec-draft-p-min','0.5'),
    @('-ngl','99','--spec-type','draft-mtp','--spec-draft-n-max','6','--spec-draft-p-min','0.75'),
    @('-ngl','99','--spec-type','draft-mtp','--spec-draft-n-max','4','--spec-draft-p-min','0.9'),
    @('-ngl','99','--spec-type','draft-mtp','--spec-draft-n-max','3','--spec-draft-p-min','0.75')
)
foreach ($cfg in $configs) {
    powershell -NoProfile -ExecutionPolicy Bypass -File E:\AI\aider\qwen\probe-config.ps1 @cfg 2>&1 |
        Where-Object { $_ -match 'PROBE|acceptance' }
}
Write-Output 'SPEC SWEEP 2 DONE'
