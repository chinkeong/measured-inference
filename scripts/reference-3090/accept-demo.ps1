# Demonstration for the guide's speculative-decoding section: same config,
# same GPU - novel generation vs verbatim copying. Shows acceptance IS the speed.
$ErrorActionPreference = 'Continue'
$novel = 'Write a single self-contained JavaScript file implementing a red-black tree class with insert, delete, search and an in-order iterator. Code only, no explanation.'
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

foreach ($t in @(@('NOVEL code generation', $novel), @('VERBATIM copying', $copy))) {
    Write-Output "===== $($t[0]) ====="
    $env:PROBE_TEXT = $t[1]
    powershell -NoProfile -ExecutionPolicy Bypass -File E:\AI\aider\qwen\probe-config.ps1 `
        -ngl 99 --spec-type draft-mtp --spec-draft-n-max 10 --spec-draft-p-min 0.5 2>&1 |
        Where-Object { $_ -match 'PROBE|acceptance' }
}
Remove-Item Env:PROBE_TEXT -ErrorAction SilentlyContinue
Write-Output 'ACCEPT DEMO DONE'
