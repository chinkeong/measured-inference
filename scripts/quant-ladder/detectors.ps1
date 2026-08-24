# detectors.ps1 - cheap disqualifiers for a quant-ladder rung.
#
#   powershell -NoProfile -ExecutionPolicy Bypass -File detectors.ps1
#              [-Manifest <path>] [-Only <rung>] [-SkipGate] [-Force]
#
# Perplexity RANKS the rungs. Detectors DISQUALIFY them: a quant can hold a
# respectable PPL and still be useless because it loops, cannot obey a format,
# or has lost its chat template. Three probes on a brief llama-server session
# (-ngl 99, -c 8192, greedy, --jinja so each model uses its OWN template,
# --reasoning off so the answer stream is what gets scanned):
#
#   (a) ~1,500-token greedy code continuation -> four lexical repetition
#       detectors, the m4 method (data/followup/m4-repetition-scan.txt), run by
#       the original m4 script so the method is identical, not a re-implementation:
#         D1 IMMEDIATE-LOOP   a k-word block repeated back-to-back >= 3x
#         D2 LINE-LOOP        identical non-trivial lines back-to-back >= 3x
#         D3 TAIL-NGRAM-16    a 16-gram from the tail recurring, tail-clustered
#         D4 GLOBAL-REPEAT-16 any 16-gram appearing >= 3x anywhere
#       D1/D2 are unambiguous decoding death spirals -> FAIL.
#       D3/D4 have documented false positives on legitimate unrolled code
#       (m4 adjudication, 2026-08-23) -> REVIEW, spot-read before ruling.
#   (b) exact-JSON echo -> does the reply parse AND match, field for field
#   (c) small code task -> does it OPEN and CLOSE a fenced block
#
# Rung verdict: FAIL on any of D1/D2/json/fence; REVIEW if only D3/D4 fired.
param(
    [string]$Manifest = 'E:\AI\measured-inference\scripts\quant-ladder\ladder-manifest.json',
    [string]$Only = '',
    [switch]$SkipGate,
    [switch]$Force,
    [int]$DeadlineMinutes = 480
)

$ErrorActionPreference = 'Continue'
$here = Split-Path -Parent $MyInvocation.MyCommand.Path
. (Join-Path $here 'ladder-lib.ps1')

$M = Get-Manifest $Manifest
$OUT = [string]$M.outdir
if (-not (Test-Path $OUT)) { New-Item -ItemType Directory -Path $OUT -Force | Out-Null }
$LEDGER = Join-Path $OUT 'results.txt'
$DET = Join-Path $OUT 'detectors.txt'
if (-not (Test-Path $DET)) {
    Set-Content -LiteralPath $DET -Value ('# detector ledger - opened {0}' -f (Get-Date -Format 's')) -Encoding utf8
}
$PORT = [int]$M.detectors.port
$DEADLINE = (Get-Date).AddMinutes($DeadlineMinutes)

# Sized to elicit ~1,500 tokens from a HEALTHY model: the first version asked for
# less and the anchor finished cleanly at 985 tokens, which is thin material for
# a repetition scan. The enumerated task list below keeps a healthy model
# producing 1,200-2,000 tokens and gives a degenerate one room to loop.
$PROBE_A = @'
Continue this JavaScript file. Write out the rest of the implementation in full, in this order: finish MinHeap (push, pop, peek, siftUp, siftDown), then class Graph (addNode, addEdge, neighbors, nodeCount), then dijkstra(graph, source) returning {dist, prev}, then reconstructPath(prev, target), then buildDemoGraph() constructing an 8-node weighted graph, then a worked example that runs dijkstra on it and prints the shortest path from A to H with its total cost. Output raw code only - no prose, no markdown fences, no commentary.

// dijkstra.js - shortest paths on a weighted directed graph.
// Self-contained: binary min-heap, graph builder, Dijkstra, path reconstruction,
// plus an 8-node worked example at the bottom.

class MinHeap {
  constructor() { this.a = []; }
  get size() { return this.a.length; }
  push(node, pri) {
'@

$PROBE_B = @'
Reply with exactly this JSON object and nothing else. No prose, no code fence, no trailing text.
{"name": "ladder", "rung": 7, "ok": true, "tags": ["a", "b"]}
'@

$PROBE_C = @'
Write a Python function median(xs) that returns the median of a list of numbers and raises ValueError on an empty list. Put the code in a single fenced python code block. Keep it short.
'@

function Test-JsonProbe {
    param([string]$Reply)
    $t = "$Reply".Trim()
    # tolerate a fence even though the prompt forbade one - the JSON parse is
    # the detector, the fence is detector (c)'s business
    $t = [regex]::Replace($t, '(?s)^\s*```[a-zA-Z]*\s*', '')
    $t = [regex]::Replace($t, '(?s)\s*```\s*$', '')
    $t = $t.Trim()
    $o = $null
    try { $o = $t | ConvertFrom-Json } catch { return @{ pass = $false; why = 'parse-error' } }
    if (-not $o) { return @{ pass = $false; why = 'empty' } }
    try {
        if ([string]$o.name -ne 'ladder') { return @{ pass = $false; why = "name=$($o.name)" } }
        if ([int]$o.rung -ne 7) { return @{ pass = $false; why = "rung=$($o.rung)" } }
        if ([bool]$o.ok -ne $true) { return @{ pass = $false; why = "ok=$($o.ok)" } }
        $tags = @($o.tags)
        if ($tags.Count -ne 2 -or [string]$tags[0] -ne 'a' -or [string]$tags[1] -ne 'b') {
            return @{ pass = $false; why = ('tags=' + ($tags -join ',')) }
        }
    } catch { return @{ pass = $false; why = 'shape-error' } }
    return @{ pass = $true; why = 'exact' }
}

function Test-FenceProbe {
    param([string]$Reply)
    $n = ([regex]::Matches("$Reply", '```')).Count
    if ($n -lt 2) { return @{ pass = $false; why = "fences=$n" } }
    if (($n % 2) -ne 0) { return @{ pass = $false; why = "fences=$n (unclosed)" } }
    $m = [regex]::Match("$Reply", '(?s)```[a-zA-Z]*\r?\n(.*?)```')
    if (-not $m.Success) { return @{ pass = $false; why = 'no well-formed block' } }
    $inner = $m.Groups[1].Value.Trim()
    if ($inner.Length -lt 20) { return @{ pass = $false; why = "block only $($inner.Length) chars" } }
    if ($inner -notmatch 'def\s+median') { return @{ pass = $false; why = 'block has no def median' } }
    return @{ pass = $true; why = "fences=$n" }
}

function Invoke-RepScan {
    param([string]$TextFile, [string]$Name)
    $scan = Join-Path $OUT ('det-{0}-repscan.txt' -f $Name)
    $errf = Join-Path $OUT ('det-{0}-repscan.err' -f $Name)
    $py = [string]$M.detectors.repcheck_py
    try {
        $p = Start-Process -FilePath 'python' -ArgumentList @($py, $TextFile) -NoNewWindow -PassThru `
            -RedirectStandardOutput $scan -RedirectStandardError $errf
        if (-not $p.WaitForExit(600000)) { try { $p.Kill() } catch {}; return $null }
    } catch {
        Write-Host ('  repscan launch failed: {0}' -f "$_")
        return $null
    }
    $txt = Get-Content -Raw -LiteralPath $scan -ErrorAction SilentlyContinue
    if (-not $txt) { return $null }
    $d1 = ([regex]::Matches($txt, '(?m)^\s*IMMEDIATE-LOOP')).Count
    $d2 = ([regex]::Matches($txt, '(?m)^\s*LINE-LOOP')).Count
    $d3 = ([regex]::Matches($txt, '(?m)^\s*TAIL-NGRAM-16')).Count
    $d4 = ([regex]::Matches($txt, '(?m)^\s*GLOBAL-REPEAT-16')).Count
    $w = [regex]::Match($txt, 'words=(\d+)')
    $u = [regex]::Match($txt, 'unique_word_ratio=([0-9.]+)')
    Remove-Item $errf -ErrorAction SilentlyContinue
    return [pscustomobject]@{
        d1 = $d1; d2 = $d2; d3 = $d3; d4 = $d4
        words = $(if ($w.Success) { [int]$w.Groups[1].Value } else { 0 })
        uniq  = $(if ($u.Success) { [double]$u.Groups[1].Value } else { 0 })
        looping = ($txt -match '\[LOOPING\]')
    }
}

function Invoke-Detectors {
    param($R)
    $name = [string]$R.name
    Write-Log ('=== DETECTORS {0} ===' -f $name)
    if (-not (Test-Path -LiteralPath ([string]$R.path))) { Write-Log ('  {0}: file gone' -f $name); return }

    $flags = [string[]]$M.detectors.server_flags
    $srv = Start-Srv -ModelPath ([string]$R.path) -Tag ('det-' + $name) -Flags $flags -Port $PORT -LogDir $OUT
    if (-not $srv) {
        Write-Ledger $DET ('DETECT {0} | verdict=SRVFAIL | the server would not come up with -ngl 99 -c 8192 (see srv-det-{0}.err.log) | ts={1}' -f $name, (Get-Date -Format 's'))
        return
    }

    $raw = Join-Path $OUT ('det-{0}-probes.txt' -f $name)
    Set-Content -LiteralPath $raw -Value ('# detector probes for {0} - {1}' -f $name, (Get-Date -Format 's')) -Encoding utf8

    # ---- (a) long greedy code continuation -> repetition scan
    $a = Invoke-Probe -Text $PROBE_A -MaxTokens ([int]$M.detectors.max_tokens_a) -Port $PORT
    $aFile = Join-Path $OUT ('det-{0}-probeA.txt' -f $name)
    $aTxt = ''
    if ($a.ok) {
        $aTxt = $a.text
        if ($a.think -and $a.think.Length -gt 0) { $aTxt = $a.think + "`n----ANSWER----`n" + $a.text }
    }
    [IO.File]::WriteAllText($aFile, $aTxt, [Text.UTF8Encoding]::new($false))
    Add-Content -LiteralPath $raw -Value ("`n===== PROBE A (code continuation, max_tokens=$($M.detectors.max_tokens_a)) =====`n" + $aTxt) -Encoding utf8

    $rep = $null
    if ($a.ok -and $aTxt.Length -gt 40) { $rep = Invoke-RepScan -TextFile $aFile -Name $name }

    # ---- (b) exact JSON echo
    $b = Invoke-Probe -Text $PROBE_B -MaxTokens 512 -Port $PORT
    $bTxt = $(if ($b.ok) { $b.text } else { '' })
    Add-Content -LiteralPath $raw -Value ("`n===== PROBE B (exact JSON) =====`n" + $bTxt) -Encoding utf8
    $jr = Test-JsonProbe -Reply $bTxt

    # ---- (c) fenced code block
    $c = Invoke-Probe -Text $PROBE_C -MaxTokens 1024 -Port $PORT
    $cTxt = $(if ($c.ok) { $c.text } else { '' })
    Add-Content -LiteralPath $raw -Value ("`n===== PROBE C (fenced block) =====`n" + $cTxt) -Encoding utf8
    $fr = Test-FenceProbe -Reply $cTxt

    Stop-Srv

    if (-not $rep) {
        $repV = 'NOSCAN'; $d1 = -1; $d2 = -1; $d3 = -1; $d4 = -1; $words = 0; $uniq = 0
    } else {
        $d1 = $rep.d1; $d2 = $rep.d2; $d3 = $rep.d3; $d4 = $rep.d4
        $words = $rep.words; $uniq = $rep.uniq
        if ($d1 -gt 0 -or $d2 -gt 0) { $repV = 'FAIL' }
        elseif ($d3 -gt 0 -or $d4 -gt 0) { $repV = 'REVIEW' }
        else { $repV = 'CLEAN' }
    }

    $verdict = 'PASS'
    if ($repV -eq 'REVIEW') { $verdict = 'REVIEW' }
    if ($repV -eq 'NOSCAN') { $verdict = 'REVIEW' }
    if ($repV -eq 'FAIL' -or -not $jr.pass -or -not $fr.pass) { $verdict = 'FAIL' }

    $pf = { param($n) if ($n -lt 0) { 'NOSCAN' } elseif ($n -eq 0) { 'PASS' } else { 'FAIL' } }
    $line = ('DETECT {0} | verdict={1} | rep={2} | D1_immediate={3}({4}) | D2_line={5}({6}) | D3_tailngram={7}({8}) | D4_globalrep={9}({10}) | json={11}({12}) | fence={13}({14}) | words={15} | uniq={16:N4} | finishA={17} | tokA={18} | tpsA={19} | thinkA={20} | load_s={21} | ts={22}' -f `
        $name, $verdict, $repV,
        (& $pf $d1), $d1, (& $pf $d2), $d2, (& $pf $d3), $d3, (& $pf $d4), $d4,
        $(if ($jr.pass) { 'PASS' } else { 'FAIL' }), $jr.why,
        $(if ($fr.pass) { 'PASS' } else { 'FAIL' }), $fr.why,
        $words, $uniq,
        $(if ($a.ok) { $a.finish } else { 'ERROR' }),
        $(if ($a.ok) { $a.predicted_n } else { 0 }),
        $(if ($a.ok) { $a.decode_tps } else { 0 }),
        $(if ($a.ok -and $a.think) { $a.think.Length } else { 0 }),
        $srv.load_s, (Get-Date -Format 's'))
    Write-Ledger $DET $line
}

# ------------------------------------------------------------------- main ----

$targets = @()
foreach ($R in ($M.rungs | Sort-Object { [int]$_.order })) {
    if ($Only -and ([string]$R.name -ne $Only)) { continue }
    if (-not $Only) {
        if (-not (Test-LedgerHas $LEDGER ('RESULT ' + $R.name + ' '))) { continue }
    }
    if ((-not $Force) -and (Test-LedgerHas $DET ('DETECT ' + $R.name + ' '))) { continue }
    $targets += $R
}
Write-Log ('detectors: {0} rung(s) to probe' -f $targets.Count)

foreach ($R in $targets) {
    if ((Get-Date) -ge $DEADLINE) { Write-Log 'deadline reached'; break }
    if (-not $SkipGate) {
        if (-not (Wait-GpuGate -Gate $M.gate -Deadline $DEADLINE)) { break }
    }
    Invoke-Detectors -R $R
}
Write-Log 'DETECTORS DONE'
