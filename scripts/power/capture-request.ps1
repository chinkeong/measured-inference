<#
.SYNOPSIS
    POST one generation to a llama-server, stamp t_start, keep the server's
    timings, and append the request-event JSONL that attribute-power.py joins
    to the power log.

.DESCRIPTION
    This script is the JOIN POINT. A power CSV alone can only tell you what the
    board drew between two wall-clock times; it cannot tell you which of those
    seconds were prefill and which were decode. The server's `timings` block
    can (prompt_ms / predicted_ms), but only if something records the wall-clock
    instant the request started. That is all this does:

        t_start  <- stamped locally, in the same local naive format nvidia-smi
                    uses, immediately BEFORE the POST
        prefill  == [t_start, t_start + prompt_ms]
        decode   == [t_start + prompt_ms, + predicted_ms]

    BIAS, STATED: t_start is stamped client-side, so HTTP round-trip and any
    server-side queueing sit INSIDE the prefill window and inflate J_prefill.
    Each event line carries `overhead_ms` = wall_ms - (prompt_ms + predicted_ms),
    which is the size of that bias; feed it back as
    `attribute-power.py --lead-ms <overhead_ms>` when it matters (it is tens of
    ms locally, negligible against a multi-second prefill, and material only for
    short prompts).

    CACHE: -CachePrompt is OFF by default. llama-server's prompt cache defaults
    to on, and a cached prefill costs almost no energy - which silently destroys
    any J/prompt-token measurement on a repeated prompt. Turn it on only when
    you are deliberately measuring the cache.

.EXAMPLE
    # one measured request, appended to an events log
    .\capture-request.ps1 -Label baseline -PromptFile .\prompts\code.txt `
        -Events .\data\power\events.jsonl -NPredict 700 -Warmup

.EXAMPLE
    # three requests in one arm, first one warms the clocks
    .\capture-request.ps1 -Label spec-n4 -Prompt "Explain B-trees." `
        -Events .\data\power\events.jsonl -Repeat 3
    # then: attribute-power.py --power power.csv --events events.jsonl --drop-first
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$Label,

    [string]$Prompt,
    [string]$PromptFile,

    [string]$BaseUrl = 'http://127.0.0.1:1234',
    [string]$Events = '.\events.jsonl',
    [string]$OutDir,

    [int]$NPredict = 512,
    [double]$Temp = 0,
    [int]$TopK = 1,
    [double]$TopP = 1.0,
    [int]$Seed = -1,

    [switch]$CachePrompt,
    [switch]$Chat,
    [string]$Model = '',
    [string]$System,

    [switch]$Warmup,
    [int]$Repeat = 1,
    [int]$SettleSeconds = 0,
    [string]$Note = ''
)

$ErrorActionPreference = 'Stop'

function Resolve-Full {
    param([string]$Path)
    $dir = Split-Path -Parent $Path
    if ([string]::IsNullOrWhiteSpace($dir)) { $dir = (Get-Location).Path }
    if (-not (Test-Path -LiteralPath $dir)) { New-Item -ItemType Directory -Path $dir -Force | Out-Null }
    return (Join-Path (Resolve-Path -LiteralPath $dir).Path (Split-Path -Leaf $Path))
}

function Add-JsonlLine {
    # .NET write with an explicit no-BOM UTF8 encoder. Add-Content -Encoding utf8
    # on PS 5.1 emits a BOM, which turns line 1 into unparseable JSON.
    param([string]$Path, [string]$Line)
    $enc = New-Object System.Text.UTF8Encoding($false)
    [System.IO.File]::AppendAllText($Path, $Line + [Environment]::NewLine, $enc)
}

function Invoke-Json {
    param([string]$Uri, [string]$Body)
    $bytes = [Text.Encoding]::UTF8.GetBytes($Body)
    $r = Invoke-WebRequest -Uri $Uri -Method Post -ContentType 'application/json' `
                           -Body $bytes -UseBasicParsing -TimeoutSec 0
    return [string]$r.Content
}

function Get-PromptText {
    if (-not [string]::IsNullOrEmpty($PromptFile)) {
        if (-not (Test-Path -LiteralPath $PromptFile)) { throw "prompt file not found: $PromptFile" }
        return (Get-Content -LiteralPath $PromptFile -Raw -Encoding UTF8)
    }
    if (-not [string]::IsNullOrEmpty($Prompt)) { return $Prompt }
    throw 'give -Prompt or -PromptFile'
}

function New-Body {
    param([string]$Text, [int]$N)
    if ($Chat) {
        $msgs = @()
        if (-not [string]::IsNullOrEmpty($System)) { $msgs += @{ role = 'system'; content = $System } }
        $msgs += @{ role = 'user'; content = $Text }
        $b = [ordered]@{
            messages     = $msgs
            max_tokens   = $N
            temperature  = $Temp
            stream       = $false
            cache_prompt = [bool]$CachePrompt
        }
        if ($Model -ne '') { $b['model'] = $Model }
    } else {
        $b = [ordered]@{
            prompt       = $Text
            n_predict    = $N
            temperature  = $Temp
            stream       = $false
            cache_prompt = [bool]$CachePrompt
        }
    }
    if ($TopK -gt 0) { $b['top_k'] = $TopK }
    if ($TopP -lt 1.0) { $b['top_p'] = $TopP }
    if ($Seed -ge 0) { $b['seed'] = $Seed }
    return ($b | ConvertTo-Json -Depth 12 -Compress)
}

function Get-Num { param($v) if ($null -eq $v) { return $null } try { return [double]$v } catch { return $null } }

# ------------------------------------------------------------------ setup
$endpoint = '/completion'
if ($Chat) { $endpoint = '/v1/chat/completions' }
$uri = $BaseUrl.TrimEnd('/') + $endpoint

$eventsFull = Resolve-Full $Events
if ([string]::IsNullOrWhiteSpace($OutDir)) { $OutDir = Split-Path -Parent $eventsFull }
if (-not (Test-Path -LiteralPath $OutDir)) { New-Item -ItemType Directory -Path $OutDir -Force | Out-Null }
$OutDir = (Resolve-Path -LiteralPath $OutDir).Path

try {
    $h = Invoke-RestMethod -Uri ($BaseUrl.TrimEnd('/') + '/health') -TimeoutSec 10
    Write-Host "server   : $BaseUrl (health=$($h.status))"
} catch {
    Write-Host "ABORT    cannot reach $BaseUrl/health : $($_.Exception.Message)"
    return
}

$text = Get-PromptText
Write-Host "label    : $Label"
Write-Host "endpoint : $endpoint"
Write-Host "prompt   : $($text.Length) chars, n_predict=$NPredict, cache_prompt=$([bool]$CachePrompt)"
Write-Host "events   : $eventsFull"

# --------------------------------------------------------------- warm-up
if ($Warmup) {
    Write-Host "warmup   : sending a throwaway 8-token request to lift the SM clock"
    Write-Host "           (measured on this box: a request off an idle board runs at"
    Write-Host "           900-990 MHz vs 1455 settled - it reads LOW-watt and fast-J/token)"
    try {
        $wb = New-Body -Text $text -N 8
        Invoke-Json -Uri $uri -Body $wb | Out-Null
        Write-Host "           warmup done (NOT recorded)"
    } catch {
        Write-Host "           warmup failed: $($_.Exception.Message)"
    }
}

# ------------------------------------------------------------------- run
$body = New-Body -Text $text -N $NPredict
$written = 0

for ($i = 1; $i -le $Repeat; $i++) {
    if ($SettleSeconds -gt 0 -and $i -gt 1) { Start-Sleep -Seconds $SettleSeconds }

    $sw = [Diagnostics.Stopwatch]::StartNew()
    $tStart = (Get-Date).ToString('yyyy-MM-ddTHH:mm:ss.fff')   # local, naive, ms - matches nvidia-smi
    try {
        $raw = Invoke-Json -Uri $uri -Body $body
    } catch {
        $sw.Stop()
        Write-Host "  [$i/$Repeat] REQUEST FAILED after $([math]::Round($sw.Elapsed.TotalSeconds,1))s : $($_.Exception.Message)"
        continue
    }
    $sw.Stop()
    $tEnd = (Get-Date).ToString('yyyy-MM-ddTHH:mm:ss.fff')
    $wallMs = [math]::Round($sw.Elapsed.TotalMilliseconds, 1)

    $resp = $raw | ConvertFrom-Json
    $t = $resp.timings

    $promptN = $null; $promptMs = $null; $predN = $null; $predMs = $null
    $draftN = $null; $draftAcc = $null; $cacheN = $null
    if ($null -ne $t) {
        $names = $t.PSObject.Properties.Name
        $promptN  = Get-Num $t.prompt_n
        $promptMs = Get-Num $t.prompt_ms
        $predN    = Get-Num $t.predicted_n
        $predMs   = Get-Num $t.predicted_ms
        if ($names -contains 'cache_n')          { $cacheN   = Get-Num $t.cache_n }
        if ($names -contains 'draft_n')          { $draftN   = Get-Num $t.draft_n }
        if ($names -contains 'draft_n_accepted') { $draftAcc = Get-Num $t.draft_n_accepted }
    }
    if ($null -eq $promptN -and $null -ne $resp.tokens_evaluated) { $promptN = Get-Num $resp.tokens_evaluated }
    if ($null -eq $predN   -and $null -ne $resp.tokens_predicted) { $predN   = Get-Num $resp.tokens_predicted }
    if ($null -eq $promptN -and $null -ne $resp.usage) { $promptN = Get-Num $resp.usage.prompt_tokens }
    if ($null -eq $predN   -and $null -ne $resp.usage) { $predN   = Get-Num $resp.usage.completion_tokens }

    $overhead = $null
    if ($null -ne $promptMs -and $null -ne $predMs) {
        $overhead = [math]::Round($wallMs - ($promptMs + $predMs), 1)
    }

    $stamp = (Get-Date).ToString('yyyyMMdd-HHmmss-fff')
    $safe = ($Label -replace '[^A-Za-z0-9._-]', '_')
    $respFile = Join-Path $OutDir "req-$safe-$stamp.json"
    [System.IO.File]::WriteAllText($respFile, $raw, (New-Object System.Text.UTF8Encoding($false)))

    $ev = [ordered]@{
        t_start_iso  = $tStart
        t_end_iso    = $tEnd
        label        = $Label
        prompt_n     = $promptN
        prompt_ms    = $promptMs
        predicted_n  = $predN
        predicted_ms = $predMs
        wall_ms      = $wallMs
        overhead_ms  = $overhead
        cache_n      = $cacheN
        draft_n      = $draftN
        draft_n_acc  = $draftAcc
        seq          = $i
        endpoint     = $endpoint
        url          = $uri
        cache_prompt = [bool]$CachePrompt
        n_predict    = $NPredict
        temperature  = $Temp
        top_k        = $TopK
        prompt_chars = $text.Length
        prompt_src   = $(if ([string]::IsNullOrEmpty($PromptFile)) { 'inline' } else { (Resolve-Path -LiteralPath $PromptFile).Path })
        response     = $respFile
        note         = $Note
    }
    Add-JsonlLine -Path $eventsFull -Line ($ev | ConvertTo-Json -Depth 6 -Compress)
    $written++

    $pms = 0.0; $dms = 0.0
    if ($null -ne $promptMs) { $pms = $promptMs }
    if ($null -ne $predMs)   { $dms = $predMs }
    $tps = 0.0
    if ($dms -gt 0 -and $null -ne $predN) { $tps = [math]::Round($predN / ($dms / 1000.0), 2) }
    Write-Host ("  [$i/$Repeat] t0={0} prompt_n={1} prompt_ms={2} predicted_n={3} predicted_ms={4} => {5} tok/s (overhead {6} ms)" `
        -f $tStart, $promptN, [math]::Round($pms, 1), $predN, [math]::Round($dms, 1), $tps, $overhead)
}

Write-Host ""
Write-Host "wrote $written event(s) to $eventsFull"
Write-Host "next:"
Write-Host "  python attribute-power.py --power <power.csv> --events `"$eventsFull`" --drop-first"
