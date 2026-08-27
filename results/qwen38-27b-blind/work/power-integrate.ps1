# Phase 10 - integrate the power log over each recorded generation window.
# kWh = mean_load_watts * wall_seconds / 3.6e6. Gross draw, idle NOT subtracted;
# the idle baseline is reported separately so a reader can bound the marginal cost.
$ErrorActionPreference = 'Continue'
$DATA = 'E:\AI\measured-inference\results\qwen38-27b-blind\data'
$pw = Join-Path $DATA 'power.csv'
$out = Join-Path $DATA 'phase10.txt'
if (-not (Test-Path $pw)) { Write-Host 'no power.csv'; exit 1 }

$samples = @()
foreach ($line in (Get-Content $pw)) {
    $p = $line -split ',\s*'
    if ($p.Count -lt 2) { continue }
    $ts = $null
    if (-not [datetime]::TryParseExact($p[0].Trim(), 'yyyy/MM/dd HH:mm:ss.fff', [Globalization.CultureInfo]::InvariantCulture, [Globalization.DateTimeStyles]::None, [ref]$ts)) { continue }
    $w = 0.0
    if (-not [double]::TryParse(($p[1] -replace '[^0-9\.]',''), [ref]$w)) { continue }
    $u = 0.0
    if ($p.Count -ge 3) { [void][double]::TryParse(($p[2] -replace '[^0-9\.]',''), [ref]$u) }
    $samples += [pscustomobject]@{ t = $ts; w = $w; u = $u }
}
Write-Host ("parsed {0} power samples, {1} .. {2}" -f $samples.Count, $samples[0].t, $samples[-1].t)

# idle baseline = the first 10 samples (logger starts before any server exists)
$idle = ($samples | Select-Object -First 10 | Measure-Object -Property w -Average).Average
$lines = @()
$lines += ("IDLE_BASELINE_W {0}  (n=10 samples, no server loaded)" -f [math]::Round($idle, 1))

$res = Get-Content (Join-Path $DATA 'phase7.txt') | Select-String -Pattern '^RESULT effort-'
foreach ($r in $res) {
    $l = $r.Line
    if ($l -notmatch 't0=\[(.+?)\] t1=\[(.+?)\]') { continue }
    $t0 = [datetime]::ParseExact($matches[1], 'yyyy/MM/dd HH:mm:ss', $null)
    $t1 = [datetime]::ParseExact($matches[2], 'yyyy/MM/dd HH:mm:ss', $null)
    $lvl = ([regex]::Match($l, 'RESULT effort-(\w+) ')).Groups[1].Value
    $tok = [int]([regex]::Match($l, 'predicted_n=(\d+)')).Groups[1].Value
    $win = $samples | Where-Object { $_.t -ge $t0 -and $_.t -le $t1 }
    if ($win.Count -lt 3) { $lines += ("ENERGY {0} NO-SAMPLES" -f $lvl); continue }
    $mean = ($win | Measure-Object -Property w -Average).Average
    $max  = ($win | Measure-Object -Property w -Maximum).Maximum
    $secs = ($t1 - $t0).TotalSeconds
    $kwh  = $mean * $secs / 3.6e6
    $lines += ("ENERGY {0} n_samples={1} wall_s={2} mean_W={3} peak_W={4} kWh_per_answer={5} tokens={6} kWh_per_1k_tok={7} Wh_per_answer={8}" -f `
        $lvl, $win.Count, [math]::Round($secs,1), [math]::Round($mean,1), [math]::Round($max,1),
        [math]::Round($kwh, 6), $tok, [math]::Round($kwh / [math]::Max($tok,1) * 1000, 6), [math]::Round($kwh*1000, 3))
}
$lines | ForEach-Object { Write-Host $_ }
$lines | Set-Content $out -Encoding utf8
Write-Host 'POWER DONE'
