# Phase 3d - CONTROL: thinking tokens vs answer tokens.
# Every speed probe so far ran at the model's DEFAULT reasoning effort (xhigh)
# with a 700-token cap, so the tokens being timed were reasoning tokens, not
# the deliverable. The content labels described the TASK, not the token stream.
# This re-runs the same four contents with thinking disabled, so the tokens
# timed are the actual output, and reports both numbers side by side.
$ErrorActionPreference = 'Continue'
. 'E:\AI\measured-inference\results\qwen38-27b-blind\work\lib.ps1'
$out = Join-Path $script:DATA 'phase3d.txt'
if (-not (Test-Path $out)) { New-Item -ItemType File -Path $out | Out-Null }
$done = Get-Content $out -ErrorAction SilentlyContinue
$common = @('-c','32768','-ngl','99','--parallel','1','--load-mode','mmap','-ctk','q8_0','-ctv','q8_0')
$NOTHINK = @('--chat-template-kwargs', '{\"enable_thinking\":false}')

$verbatim = @'
function fibonacci(n) {
    if (n <= 1) return n;
    let a = 0, b = 1;
    for (let i = 2; i <= n; i++) {
        const t = a + b; a = b; b = t;
    }
    return b;
}
const memo = new Map();
function fibMemo(n) {
    if (n <= 1) return n;
    if (memo.has(n)) return memo.get(n);
    const v = fibMemo(n - 1) + fibMemo(n - 2);
    memo.set(n, v);
    return v;
}
for (let i = 0; i < 30; i++) console.log(i, fibonacci(i), fibMemo(i));
'@
$prompts = @(
    @{ id='code-js';  text=$script:CODE_PROBE },
    @{ id='code-py';  text='Write a single self-contained Python module implementing a thread-safe LRU cache with per-entry TTL expiry, plus unittest tests for it. Code only, no explanation.' },
    @{ id='prose';    text='Write a detailed 500-word technical explanation of how a marine aquarium nitrogen cycle works.' },
    @{ id='verbatim'; text=("Repeat the following code verbatim, exactly as written, 3 times in a row. Output only the code, no commentary:`n`n" + $verbatim) }
)
$cfgs = @(
    @{ tag='nothink-none';     extra=@('--spec-type','none') },
    @{ tag='nothink-n10-p0.5'; extra=@('--spec-type','draft-mtp','--spec-draft-n-max','10','--spec-draft-p-min','0.5') },
    @{ tag='nothink-n4-p0.75'; extra=@('--spec-type','draft-mtp','--spec-draft-n-max','4','--spec-draft-p-min','0.75') }
)
foreach ($c in $cfgs) {
    if ($done -match ("^RESULT " + [regex]::Escape($c.tag) + "/verbatim ")) { Write-Host "skip $($c.tag)"; continue }
    Write-Host "=== $($c.tag) ==="
    $s = Start-Srv -Extra ($common + $NOTHINK + $c.extra) -Tag $c.tag
    if (-not $s) { Write-Row $out ("RESULT {0} LOAD-FAILED" -f $c.tag); continue }
    foreach ($p in $prompts) {
        $r = Invoke-Probe -Text $p.text -MaxTokens 700
        $acc = 'n/a'
        if ($r.draft_n -and [double]$r.draft_n -gt 0) { $acc = [math]::Round([double]$r.draft_acc / [double]$r.draft_n, 4) }
        $head = ($r.text -replace "`r?`n", ' ')
        if ($head.Length -gt 110) { $head = $head.Substring(0,110) }
        Write-Row $out ("RESULT {0}/{1} decode_tps={2} predicted_n={3} accept={4} draft_n={5} draft_acc_n={6} answer_chars={7} think_chars={8} finish={9}" -f `
            $c.tag, $p.id, $r.decode_tps, $r.predicted_n, $acc, $r.draft_n, $r.draft_acc, $r.text.Length, $r.think.Length, $r.finish)
        Write-Row $out ("  HEAD {0}/{1}| {2}" -f $c.tag, $p.id, $head)
    }
    Stop-Srv
}
Write-Host 'PHASE3D DONE'
