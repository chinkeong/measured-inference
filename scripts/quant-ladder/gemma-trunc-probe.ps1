# gemma-trunc-probe.ps1 - is the gemma runaway the MODEL or the HARNESS?
#
# ESTABLISHED WITHOUT THE GPU (from the two decisive-arm runs):
#   * The cap knob took effect: max_tokens 16,384 -> 32,768, -c 32,768 -> 65,536,
#     wall 5,353 s -> 9,543 s, and ALL 19 truncated items hit EXACTLY 32,768
#     tokens. 19/19 ran to whatever cap they were given.
#   * All 19 truncated completions record chars=0. bench.py stores
#     msg["content"] only (bench.py:225), and llama-server with --jinja splits
#     thinking into reasoning_content - so an empty completion at the cap means
#     the runaway happened INSIDE an unterminated thinking block.
#   * 56/75 completions terminated normally (206 / 1,147 / 9,007 tokens
#     min/median/max), so end-of-turn works for most prompts.
#   * Qwen on the identical suite and identical harness: 0-2 truncations at the
#     same 32k cap. Same harness, different outcome -> the harness is not the
#     whole story.
#
# WHAT THIS PROBE ADDS (the part artifacts cannot answer): the reasoning text was
# never saved, so nothing on disk shows WHAT gemma emitted. Two short sessions:
#   ARM raw   : --reasoning-format none leaves the thoughts UNPARSED in content,
#               so the raw stream is visible - is it a repetition loop, and does
#               it ever emit an end-of-thinking marker?
#   ARM off   : --reasoning off disables thinking. If the same prompt then
#               terminates cleanly, the runaway lives in the thinking block and
#               is a property of gemma-4-it's DEFAULT behaviour, not of the
#               scorer.
#
# GPU-gated: the ladder owns the card first.
param(
    [string]$Manifest = 'E:\AI\measured-inference\scripts\quant-ladder\ladder-manifest.json',
    [int]$MaxTokens = 4096,
    [int]$DeadlineMinutes = 240
)
$ErrorActionPreference = 'Continue'
$here = Split-Path -Parent $MyInvocation.MyCommand.Path
. (Join-Path $here 'ladder-lib.ps1')

$M = Get-Manifest $Manifest
$OUT = Join-Path ([string]$M.outdir) 'gemma-trunc'
if (-not (Test-Path $OUT)) { New-Item -ItemType Directory -Path $OUT -Force | Out-Null }
$LED = Join-Path $OUT 'trunc-probe.txt'
if (-not (Test-Path $LED)) { Set-Content -LiteralPath $LED -Value ('# gemma truncation probe - opened {0}' -f (Get-Date -Format 's')) -Encoding utf8 }
$DEADLINE = (Get-Date).AddMinutes($DeadlineMinutes)
$GEMMA = 'C:\Users\chink\.lmstudio\models\lmstudio-community\gemma-4-12B-it-QAT-GGUF\gemma-4-12B-it-QAT-Q4_0.gguf'
$PORT = 1235

# Pull the offending prompts straight out of the recorded transcripts - never
# retyped, so the probe asks EXACTLY what the benchmark asked.
$bench = Join-Path ([string]$M.outdir) 'bench'
$tf = Get-ChildItem $bench -Filter 'arm-gemma-12b-qat-q4_0-gemma*_transcripts.json' | Sort-Object Name | Select-Object -Last 1
$tr = (Get-Content -Raw $tf.FullName | ConvertFrom-Json).generations
# MBPP[0] and GSM8K[6] are both in the truncated 19
$cases = @(
    @{ ds = 'MBPP';  idx = 0 },
    @{ ds = 'GSM8K'; idx = 6 }
)

$arms = @(
    @{ tag = 'raw'; flags = @('-ngl','99','-c','65536','-fa','on','--parallel','1','--jinja','--reasoning-format','none') },
    @{ tag = 'off'; flags = @('-ngl','99','-c','65536','-fa','on','--parallel','1','--jinja','--reasoning','off') }
)

foreach ($a in $arms) {
    if ((Get-Date) -ge $DEADLINE) { break }
    if (Test-LedgerHas $LED ('PROBE ' + $a.tag + '-')) { Write-Log ('skip arm {0} (done)' -f $a.tag); continue }
    if (-not (Wait-GpuGate -Gate $M.gate -Deadline $DEADLINE)) { Write-Log 'gate never opened'; break }
    $srv = Start-Srv -ModelPath $GEMMA -Tag ('gtrunc-' + $a.tag) -Flags $a.flags -Port $PORT -LogDir $OUT
    if (-not $srv) { Write-Ledger $LED ('PROBE {0} | SRVFAIL' -f $a.tag); continue }
    foreach ($c in $cases) {
        $entry = $tr.($c.ds) | Where-Object { $_.index -eq $c.idx } | Select-Object -First 1
        if (-not $entry) { Write-Log ('no transcript for {0}[{1}]' -f $c.ds, $c.idx); continue }
        $r = Invoke-Probe -Text ([string]$entry.prompt) -MaxTokens $MaxTokens -Port $PORT -TimeoutSec 1800
        $tag2 = ('{0}-{1}{2}' -f $a.tag, $c.ds, $c.idx)
        $body = ''
        if ($r.ok) {
            $body = [string]$r.text
            if ($r.think) { $body = "----REASONING (" + $r.think.Length + " chars)----`n" + $r.think + "`n----CONTENT----`n" + [string]$r.text }
        }
        [IO.File]::WriteAllText((Join-Path $OUT ('probe-{0}.txt' -f $tag2)), $body, [Text.UTF8Encoding]::new($false))
        # does the raw stream ever close a thinking block?
        $openTag = ([regex]::Matches($body, '(?i)<\s*(think|thought|reasoning)[^>]*>')).Count
        $closeTag = ([regex]::Matches($body, '(?i)<\s*/\s*(think|thought|reasoning)\s*>')).Count
        $eot = ([regex]::Matches($body, '<end_of_turn>|<eos>|<\|im_end\|>')).Count
        Write-Ledger $LED ('PROBE {0} | finish={1} | predicted_n={2} | content_chars={3} | think_chars={4} | open_think_tags={5} | close_think_tags={6} | eot_markers={7} | tps={8}' -f `
            $tag2,
            $(if ($r.ok) { $r.finish } else { 'ERROR' }),
            $(if ($r.ok) { $r.predicted_n } else { 0 }),
            $(if ($r.ok) { ([string]$r.text).Length } else { -1 }),
            $(if ($r.ok -and $r.think) { $r.think.Length } else { 0 }),
            $openTag, $closeTag, $eot,
            $(if ($r.ok) { $r.decode_tps } else { 0 }))
    }
    Stop-Srv
}
Write-Log 'GEMMA-TRUNC-PROBE DONE'
