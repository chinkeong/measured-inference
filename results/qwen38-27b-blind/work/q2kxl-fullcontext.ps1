# q2kxl-fullcontext.ps1 - can the 2.9-bpw file hold this model's FULL native
# 262,144-token window on a 24 GB card, with the drafter on and a desktop up?
#
# WHY THIS ARM EXISTS. The published guide says full native 262,144 is
# headless-only and needs --spec-type none, because UD-IQ4_XS at 13.274 GiB
# plus 9.75 GiB of KV is 23.02 GiB before the desktop gets anything. UD-Q2_K_XL
# is 4.12 GiB smaller and the same arithmetic puts it at 18.90 GiB drafter-off
# and 21.14 GiB drafter-on. If that holds, the 2.9-bpw file buys something the
# 4-bit file cannot have at any speed: the whole window, with speculation, on a
# machine you are also using.
#
# THAT IS ARITHMETIC, AND RULE 13b FORBIDS SHIPPING IT AS A WINDOW LABEL. No
# window is called resident without a deep-fill probe near its top - a blind
# reproduction already caught a window labelled "fully resident" collapsing to
# 8 t/s at depth once the drafter's VRAM was on board. So: measure the VRAM as
# a drafter on/off PAIR (rule 13a), fill to ~90% of the window with real
# tokens, discard the first post-prefill probe (rule 12), and time only settled
# ones.
#
# Rule 25 who-consumes: the 24 GB recipe recommendation in section 03 of the
# published guide, and the answer to a reader asking whether a smaller file is
# worth it for long context rather than for speed.
param([int]$DeadlineMinutes = 90, [int]$MaxVramMiB = 2000)
$ErrorActionPreference = 'Continue'
. 'E:\AI\measured-inference\scripts\quant-ladder\ladder-lib.ps1'

$M      = 'C:\Users\chink\.lmstudio\models\unsloth\Qwen3.8-27B-GGUF'
$CORPUS = 'E:\AI\measured-inference\corpora\wikitext-2-raw-test.raw'
$DATA   = 'E:\AI\measured-inference\results\qwen38-27b-blind\data\quant-ladder'
$OUT    = Join-Path $DATA 'fullcontext'
if (-not (Test-Path $OUT)) { New-Item -ItemType Directory -Path $OUT -Force | Out-Null }
$LED = Join-Path $OUT 'fullcontext.txt'
if (-not (Test-Path $LED)) {
    Set-Content -LiteralPath $LED -Encoding utf8 -Value ('# full-native-window trial, UD-Q2_K_XL vs UD-IQ4_XS - opened {0}' -f (Get-Date -Format 's'))
}
$PORT = 1235
$DEADLINE = (Get-Date).AddMinutes($DeadlineMinutes)

# ~236k tokens of REAL text (~90% of 262,144). 4 chars/token is the campaign's
# coarse estimate; the server's own prompt_n is what gets recorded.
$raw = [IO.File]::ReadAllText($CORPUS)
$need = 236000 * 4
if ($raw.Length -lt $need) { $raw = $raw * [math]::Ceiling($need / $raw.Length) }
$FILL = $raw.Substring(0, $need) + "`n`nIn one sentence, name the single most frequent topic in the text above."

$ARMS = @(
    @{ tag = 'q2kxl-262k-on';  file = "$M\Qwen3.8-27B-UD-Q2_K_XL.gguf"; ctx = 262144; spec = @('--spec-type','draft-mtp','--spec-draft-n-max','4','--spec-draft-p-min','0.75') },
    @{ tag = 'q2kxl-262k-off'; file = "$M\Qwen3.8-27B-UD-Q2_K_XL.gguf"; ctx = 262144; spec = @('--spec-type','none') },
    @{ tag = 'iq4xs-262k-off'; file = "$M\Qwen3.8-27B-UD-IQ4_XS.gguf";  ctx = 262144; spec = @('--spec-type','none') }
)

while ((Get-Date) -lt $DEADLINE) {
    $procs = @(Get-Process -Name 'llama-server','llama-perplexity','llama-cli','llama-bench' -ErrorAction SilentlyContinue).Count
    $v = 999999; try { $v = [int](& nvidia-smi --query-gpu=memory.used --format=csv,noheader,nounits | Select-Object -First 1) } catch {}
    if ($procs -eq 0 -and $v -lt $MaxVramMiB) { break }
    Write-Log ('waiting for the card - procs={0} vram={1}' -f $procs, $v); Start-Sleep -Seconds 45
}

foreach ($a in $ARMS) {
    if ((Get-Date) -ge $DEADLINE) { break }
    if (Test-LedgerHas $LED ('CTX ' + $a.tag + ' ')) { Write-Log ('skip ' + $a.tag); continue }
    $flags = @('-ngl','99','-c',"$($a.ctx)",'-fa','on','--parallel','1',
               '-ctk','q8_0','-ctv','q8_0','--jinja','--reasoning','off') + $a.spec
    $srv = Start-Srv -ModelPath $a.file -Tag ('fc-' + $a.tag) -Flags $flags -Port $PORT -LogDir $OUT
    if (-not $srv) { Write-Ledger $LED ('CTX {0} | SRVFAIL - did not load at -c {1}' -f $a.tag, $a.ctx); continue }

    Start-Sleep -Seconds 5
    $board = 0; try { $board = [int](& nvidia-smi --query-gpu=memory.used --format=csv,noheader,nounits | Select-Object -First 1) } catch {}

    # deep fill near the top of the window, then settled probes (rules 12/13b)
    $first = Invoke-Probe -Text $FILL -MaxTokens 120 -Port $PORT -TimeoutSec 1800
    $deepBoard = 0; try { $deepBoard = [int](& nvidia-smi --query-gpu=memory.used --format=csv,noheader,nounits | Select-Object -First 1) } catch {}
    Start-Sleep -Seconds 20
    $rs = @()
    for ($i = 0; $i -lt 2; $i++) {
        $r = Invoke-Probe -Text $FILL -MaxTokens 120 -Port $PORT -TimeoutSec 1800
        if ($r.ok) { $rs += $r }
        Start-Sleep -Seconds 5
    }
    Stop-Srv

    if (-not $rs.Count) {
        Write-Ledger $LED ('CTX {0} | loaded board={1} MiB but NO settled probe returned (first probe ok={2})' -f $a.tag, $board, $first.ok)
        continue
    }
    $tps  = ($rs | Measure-Object -Property decode_tps -Average).Average
    $pn   = ($rs | Measure-Object -Property prompt_n -Average).Average
    $len = 'n/a'
    $el = Join-Path $OUT ('srv-fc-{0}.err.log' -f $a.tag)
    if (Test-Path $el) {
        $t = Get-Content -Raw $el
        $ml = [regex]::Matches($t, 'mean len =\s*([\d.]+)')
        if ($ml.Count) { $len = $ml[$ml.Count-1].Groups[1].Value }
    }
    Write-Ledger $LED ('CTX {0} | ctx={1} | board_at_load={2} MiB | board_at_depth={3} MiB | slack={4} MiB | prompt_n={5:N0} | decode_at_depth={6:N2} t/s | first_probe_tps={7} | settled_probes={8} | mean_draft_len={9} | load_s={10}' -f `
        $a.tag, $a.ctx, $board, $deepBoard, (24576 - $deepBoard), $pn, $tps,
        $(if ($first.ok) { [math]::Round($first.decode_tps,2) } else { 'ERR' }), $rs.Count, $len, $srv.load_s)
}
Write-Log 'FULLCONTEXT DONE'
