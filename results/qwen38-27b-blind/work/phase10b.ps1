# Phase 10b - per-recipe power and VRAM verification.
# REPORT-SPEC section 8 wants a measured watts-under-load and kWh-per-answer
# column PER SHIPPED RECIPE, not one figure borrowed across all of them.
# For each recipe: fresh server, 1 Hz power log around one identical
# generation, integrate over the generation window only.
$ErrorActionPreference = 'Continue'
. 'E:\AI\measured-inference\results\qwen38-27b-blind\work\lib.ps1'
$out = Join-Path $script:DATA 'phase10b.txt'
if (-not (Test-Path $out)) { New-Item -ItemType File -Path $out | Out-Null }
$done = Get-Content $out -ErrorAction SilentlyContinue

$SPEC_CODE  = @('--spec-type','draft-mtp','--spec-draft-n-max','10','--spec-draft-p-min','0.5')
$SPEC_PROSE = @('--spec-type','draft-mtp','--spec-draft-n-max','4','--spec-draft-p-min','0.75')
$COMMON = @('-ngl','99','--parallel','1','--load-mode','mmap','-ctk','q8_0','-ctv','q8_0','--reasoning-preserve')
$MM = @('--mmproj', $script:MMPROJ, '--image-min-tokens','1024')

$recipes = @(
    @{ id='R1-code-vision-163840'; extra=(@('-c','163840') + $COMMON + $MM + $SPEC_CODE) },
    @{ id='R2-desktop-safe-131072'; extra=(@('-c','131072') + $COMMON + $MM + $SPEC_CODE) },
    @{ id='R3-textonly-180224';     extra=(@('-c','180224') + $COMMON + $SPEC_CODE) },
    @{ id='R4-prose-131072';        extra=(@('-c','131072') + $COMMON + $MM + $SPEC_PROSE) },
    # R1 with the conservative drafter: Phase 3d may show that n4/p0.75 is the
    # better ship for real ANSWER tokens (the earlier sweep timed reasoning
    # tokens). Measure both so whichever wins already has its VRAM and power.
    @{ id='R1b-code-vision-163840-n4'; extra=(@('-c','163840') + $COMMON + $MM + $SPEC_PROSE) }
)

# idle baseline first
$idleCsv = Join-Path $script:DATA 'power-idle.csv'
Stop-Srv
$lg = Start-Process -FilePath 'nvidia-smi' -ArgumentList @('--query-gpu=timestamp,power.draw','--format=csv,noheader','-l','1') `
    -WindowStyle Hidden -RedirectStandardOutput $idleCsv -RedirectStandardError (Join-Path $script:DATA 'power-idle.err') -PassThru
Start-Sleep -Seconds 15
try { $lg | Stop-Process -Force -Confirm:$false } catch {}

function Get-MeanW {
    param([string]$Csv, [datetime]$T0, [datetime]$T1)
    $ws = @()
    foreach ($line in (Get-Content $Csv -ErrorAction SilentlyContinue)) {
        $p = $line -split ',\s*'
        if ($p.Count -lt 2) { continue }
        $ts = [datetime]::MinValue
        if (-not [datetime]::TryParseExact($p[0].Trim(), 'yyyy/MM/dd HH:mm:ss.fff', [Globalization.CultureInfo]::InvariantCulture, [Globalization.DateTimeStyles]::None, [ref]$ts)) { continue }
        if ($T0 -ne [datetime]::MinValue -and ($ts -lt $T0 -or $ts -gt $T1)) { continue }
        $w = 0.0
        if ([double]::TryParse(($p[1] -replace '[^0-9\.]',''), [ref]$w)) { $ws += $w }
    }
    if ($ws.Count -eq 0) { return $null }
    return [pscustomobject]@{ n = $ws.Count
        mean = [math]::Round((($ws | Measure-Object -Average).Average), 1)
        max  = [math]::Round((($ws | Measure-Object -Maximum).Maximum), 1) }
}
$idle = Get-MeanW -Csv $idleCsv -T0 ([datetime]::MinValue) -T1 ([datetime]::MaxValue)
if ($idle) { Write-Row $out ("IDLE_W mean={0} peak={1} n={2} (no server loaded)" -f $idle.mean, $idle.max, $idle.n) }

foreach ($r in $recipes) {
    if ($done -match ("^RESULT " + [regex]::Escape($r.id) + " ")) { Write-Host "skip $($r.id)"; continue }
    Write-Host "=== $($r.id) ==="
    $s = Start-Srv -Extra $r.extra -Tag $r.id -TimeoutSec 600
    if (-not $s) { Write-Row $out ("RESULT {0} LOAD-FAILED" -f $r.id); continue }
    $v = Get-Vram
    Start-Sleep -Seconds 3
    $csv = Join-Path $script:DATA ("power-" + $r.id + ".csv")
    $lg2 = Start-Process -FilePath 'nvidia-smi' -ArgumentList @('--query-gpu=timestamp,power.draw','--format=csv,noheader','-l','1') `
        -WindowStyle Hidden -RedirectStandardOutput $csv -RedirectStandardError (Join-Path $script:DATA 'power-r.err') -PassThru
    # server loaded but generating nothing - the number a reader's box will
    # sit at between requests
    $i0 = Get-Date
    Start-Sleep -Seconds 10
    $i1 = Get-Date
    $t0 = Get-Date
    $probe = Invoke-Probe -Text $script:CODE_PROBE -MaxTokens 700
    $t1 = Get-Date
    Start-Sleep -Seconds 2
    try { $lg2 | Stop-Process -Force -Confirm:$false } catch {}
    $p = Get-MeanW -Csv $csv -T0 $t0 -T1 $t1
    $li = Get-MeanW -Csv $csv -T0 $i0 -T1 $i1
    if ($li) { Write-Row $out ("  LOADED_IDLE_W {0} mean={1} peak={2} n={3}" -f $r.id, $li.mean, $li.max, $li.n) }
    $acc = 'n/a'
    if ($probe.draft_n -and [double]$probe.draft_n -gt 0) { $acc = [math]::Round([double]$probe.draft_acc / [double]$probe.draft_n, 4) }
    $secs = ($t1 - $t0).TotalSeconds
    $meanW = 0; $peakW = 0; $ns = 0
    if ($p) { $meanW = $p.mean; $peakW = $p.max; $ns = $p.n }
    $kwh = $meanW * $secs / 3.6e6
    Write-Row $out ("RESULT {0} decode_tps={1} accept={2} predicted_n={3} wall_s={4} board_mib={5} srv_ded_mib={6} srv_shr_mib={7} mean_W={8} peak_W={9} n_samples={10} kWh_per_answer={11} Wh_per_answer={12} kWh_per_1k_tok={13}" -f `
        $r.id, $probe.decode_tps, $acc, $probe.predicted_n, [math]::Round($secs,2), $v.board_mib, $v.srv_ded_mib, $v.srv_shr_mib,
        $meanW, $peakW, $ns, [math]::Round($kwh,7), [math]::Round($kwh*1000,4), [math]::Round($kwh / [math]::Max($probe.predicted_n,1) * 1000, 7))
    Stop-Srv
}
Write-Host 'PHASE10B DONE'
