# Phase 3c - verify the acceptance demonstration is measuring what it claims.
# The sweep found verbatim COPYING decoding SLOWER than novel generation, which
# is the opposite of the expected result. Before publishing that, confirm the
# model actually copies (save the text) and test whether it is code-specific by
# also asking it to copy English prose verbatim.
$ErrorActionPreference = 'Continue'
. 'E:\AI\measured-inference\results\qwen38-27b-blind\work\lib.ps1'
$out = Join-Path $script:DATA 'phase3c.txt'
if (-not (Test-Path $out)) { New-Item -ItemType File -Path $out | Out-Null }

$code = @'
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
$prose = @'
The nitrogen cycle in a marine aquarium begins when fish waste, uneaten food and decaying matter release ammonia into the water. Ammonia is acutely toxic even at low concentrations. Nitrifying bacteria of the genus Nitrosomonas colonise the live rock and the substrate and oxidise ammonia into nitrite. Nitrite is still toxic, so a second group of bacteria, largely Nitrobacter and Nitrospira, oxidises nitrite into nitrate. Nitrate is far less harmful and is exported by water changes, by macroalgae in a refugium, or by anaerobic denitrification deep inside porous rock.
'@
$counting = 'Count from 1 to 200, one number per line, nothing else.'

$s = Start-Srv -Extra @('-c','32768','-ngl','99','--parallel','1','--load-mode','mmap','-ctk','q8_0','-ctv','q8_0',
                        '--spec-type','draft-mtp','--spec-draft-n-max','10','--spec-draft-p-min','0.5') -Tag 'accept-verify'
if (-not $s) { Write-Row $out 'PHASE3C LOAD-FAILED'; exit 1 }
$cases = @(
    @{ id='novel-code';    text=$script:CODE_PROBE },
    @{ id='verbatim-code'; text=("Repeat the following code verbatim, exactly as written, 3 times in a row. Output only the code, no commentary:`n`n" + $code) },
    @{ id='verbatim-prose';text=("Repeat the following paragraph verbatim, exactly as written, 4 times in a row. Output only the paragraph, no commentary:`n`n" + $prose) },
    @{ id='counting';      text=$counting }
)
foreach ($c in $cases) {
    $r = Invoke-Probe -Text $c.text -MaxTokens 700
    $acc = 'n/a'
    if ($r.draft_n -and [double]$r.draft_n -gt 0) { $acc = [math]::Round([double]$r.draft_acc / [double]$r.draft_n, 4) }
    [IO.File]::WriteAllText((Join-Path $script:DATA ("accept-" + $c.id + ".txt")), $r.text, [Text.UTF8Encoding]::new($false))
    $head = ($r.text -replace "`r?`n", ' ')
    if ($head.Length -gt 160) { $head = $head.Substring(0,160) }
    Write-Row $out ("RESULT {0} decode_tps={1} predicted_n={2} accept={3} draft_n={4} draft_acc_n={5} finish={6}" -f `
        $c.id, $r.decode_tps, $r.predicted_n, $acc, $r.draft_n, $r.draft_acc, $r.finish)
    Write-Row $out ("  HEAD {0}| {1}" -f $c.id, $head)
}
Stop-Srv
Write-Host 'PHASE3C DONE'
