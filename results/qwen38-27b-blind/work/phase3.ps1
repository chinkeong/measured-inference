# Phase 3 — speed: baseline, MTP speculation sweep, acceptance demonstration.
# Fresh server per config (the flags are load-time). temp 0 / top_k 1 code probe.
# Resumable on RESULT lines.
$ErrorActionPreference = 'Continue'
. 'E:\AI\measured-inference\results\qwen38-27b-blind\work\lib.ps1'
$out = Join-Path $script:DATA 'phase3.txt'
if (-not (Test-Path $out)) { New-Item -ItemType File -Path $out | Out-Null }
$done = Get-Content $out -ErrorAction SilentlyContinue
$common = @('-c','32768','-ngl','99','--parallel','1','--load-mode','mmap','-ctk','q8_0','-ctv','q8_0')

$cfgs = @(
    @{ tag='spec-none';       extra=@('--spec-type','none') },
    @{ tag='mtp-n3-p0';       extra=@('--spec-type','draft-mtp','--spec-draft-n-max','3','--spec-draft-p-min','0') },
    @{ tag='mtp-n4-p0.75';    extra=@('--spec-type','draft-mtp','--spec-draft-n-max','4','--spec-draft-p-min','0.75') },
    @{ tag='mtp-n6-p0.5';     extra=@('--spec-type','draft-mtp','--spec-draft-n-max','6','--spec-draft-p-min','0.5') },
    @{ tag='mtp-n10-p0';      extra=@('--spec-type','draft-mtp','--spec-draft-n-max','10','--spec-draft-p-min','0') },
    @{ tag='mtp-n10-p0.5';    extra=@('--spec-type','draft-mtp','--spec-draft-n-max','10','--spec-draft-p-min','0.5') },
    @{ tag='mtp-n10-p0.75';   extra=@('--spec-type','draft-mtp','--spec-draft-n-max','10','--spec-draft-p-min','0.75') },
    @{ tag='mtp-n16-p0.5';    extra=@('--spec-type','draft-mtp','--spec-draft-n-max','16','--spec-draft-p-min','0.5') }
)

function Show-Res {
    param($tag, $r, $out)
    $acc = 'n/a'
    if ($r.draft_n -and [double]$r.draft_n -gt 0) { $acc = [math]::Round([double]$r.draft_acc / [double]$r.draft_n, 4) }
    Write-Row $out ("RESULT {0} decode_tps={1} prefill_tps={2} prompt_n={3} predicted_n={4} wall_s={5} draft_n={6} draft_acc_n={7} accept={8} finish={9}" -f `
        $tag, $r.decode_tps, $r.prefill_tps, $r.prompt_n, $r.predicted_n, $r.wall_s, $r.draft_n, $r.draft_acc, $acc, $r.finish)
}

foreach ($c in $cfgs) {
    if ($done -match ("^RESULT " + [regex]::Escape($c.tag) + " ")) { Write-Host "skip $($c.tag)"; continue }
    Write-Host "=== $($c.tag) ==="
    $s = Start-Srv -Extra ($common + $c.extra) -Tag $c.tag
    if (-not $s) { Write-Row $out ("RESULT {0} LOAD-FAILED" -f $c.tag); continue }
    $r = Invoke-Probe -Text $script:CODE_PROBE -MaxTokens 700
    Show-Res $c.tag $r $out
    $sl = @()
    foreach ($f in @($s.err, $s.out)) { if (Test-Path $f) { $sl += (Select-String -Path $f -Pattern 'accept|draft|spec' | ForEach-Object { $_.Line.Trim() } | Select-Object -Last 4) } }
    foreach ($l in ($sl | Select-Object -Unique)) { Write-Row $out ("  LOG {0}| {1}" -f $c.tag, $l) }
    Stop-Srv
}

# ---- acceptance demonstration: same server, same flags, two content types ----
if (-not ($done -match '^RESULT accept-verbatim ')) {
    Write-Host '=== acceptance demonstration ==='
    $s = Start-Srv -Extra ($common + @('--spec-type','draft-mtp','--spec-draft-n-max','10','--spec-draft-p-min','0.5')) -Tag 'accept-demo'
    if ($s) {
        $sample = @'
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
        $copy = "Repeat the following code verbatim, exactly as written, 3 times in a row. Output only the code, no commentary:`n`n$sample"
        $r1 = Invoke-Probe -Text $script:CODE_PROBE -MaxTokens 700
        Show-Res 'accept-novel' $r1 $out
        $r2 = Invoke-Probe -Text $copy -MaxTokens 700
        Show-Res 'accept-verbatim' $r2 $out
        Stop-Srv
    } else { Write-Row $out 'RESULT accept-demo LOAD-FAILED' }
}
Write-Host 'PHASE3 DONE'
