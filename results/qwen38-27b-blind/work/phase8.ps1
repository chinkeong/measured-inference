# Phase 8 (reduced) - vision: resolution -> token cost of ONE 1440p
# Chrome-headless screenshot of a local HTML file, via a direct API image_url
# request. Image token cost = prompt_tokens(text+image) - prompt_tokens(text).
# Two server arms: default image-token budget, and a capped one, to show the
# knob moves the price.
$ErrorActionPreference = 'Continue'
. 'E:\AI\measured-inference\results\qwen38-27b-blind\work\lib.ps1'
$out = Join-Path $script:DATA 'phase8.txt'
if (-not (Test-Path $out)) { New-Item -ItemType File -Path $out | Out-Null }

$chrome = 'C:\Program Files\Google\Chrome\Application\chrome.exe'
$page = $env:PH8_PAGE
# prefer the low-effort page: it renders a densely populated scene, so a
# reply that names real content is actually falsifiable. (The medium page has
# an initialisation bug that leaves most of the frame empty - see section 04.)
if (-not $page) { $page = Join-Path $script:DATA 'effort-low.html' }
if (-not (Test-Path $page)) { $page = Join-Path $script:DATA 'effort-medium.html' }
if (-not (Test-Path $page)) { Write-Row $out 'PHASE8 NO PAGE TO SHOOT'; exit 1 }
$shot = Join-Path $script:DATA 'shot-1440p.png'
$prof = Join-Path $script:DATA 'chrome-profile'

Remove-Item $shot -ErrorAction SilentlyContinue
$uri = ([uri]("file:///" + ($page -replace '\\','/'))).AbsoluteUri
& $chrome --headless=new --disable-gpu --no-sandbox --hide-scrollbars `
    --user-data-dir="$prof" --virtual-time-budget=6000 `
    --screenshot="$shot" --window-size=2560,1440 $uri 2>&1 | Out-Null
Start-Sleep -Seconds 3
if (-not (Test-Path $shot)) { Write-Row $out 'PHASE8 SCREENSHOT FAILED'; exit 1 }
Add-Type -AssemblyName System.Drawing
$img = [System.Drawing.Image]::FromFile($shot)
$W = $img.Width; $H = $img.Height; $img.Dispose()
$bytes = (Get-Item $shot).Length
Write-Row $out ("SHOT page={0} px={1}x{2} png_bytes={3}" -f (Split-Path $page -Leaf), $W, $H, $bytes)

$b64 = 'data:image/png;base64,' + [Convert]::ToBase64String([IO.File]::ReadAllBytes($shot))
$q = 'Describe this screenshot in two sentences: what kind of page is it, and name three distinct things visible in it.'

$arms = @(
    @{ tag='vis-default'; extra=@() },
    @{ tag='vis-cap1024'; extra=@('--image-max-tokens','1024') }
)
foreach ($a in $arms) {
    Write-Host "=== $($a.tag) ==="
    # thinking OFF: at default xhigh the model spends the whole cap reasoning
    # and returns an empty content field, which would tell us nothing about
    # whether it saw the image.
    $extra = @('-c','65536','-ngl','99','--parallel','1','--load-mode','mmap','-ctk','q8_0','-ctv','q8_0',
               '--mmproj', $script:MMPROJ, '--chat-template-kwargs', '{\"enable_thinking\":false}',
               '--spec-type','draft-mtp','--spec-draft-n-max','4','--spec-draft-p-min','0.75') + $a.extra
    $s = Start-Srv -Extra $extra -Tag $a.tag -TimeoutSec 600
    if (-not $s) { Write-Row $out ("RESULT {0} LOAD-FAILED" -f $a.tag); continue }
    $v = Get-Vram
    $base = Invoke-Probe -Text $q -MaxTokens 8
    $withImg = Invoke-Probe -Text $q -MaxTokens 400 -ExtraContent @(@{ type='image_url'; image_url=@{ url=$b64 } })
    $imgTok = [int]$withImg.prompt_n - [int]$base.prompt_n
    Write-Row $out ("RESULT {0} text_prompt_n={1} img_prompt_n={2} image_tokens={3} prefill_tps={4} prefill_s={5} decode_tps={6} board_mib={7} srv_ded_mib={8}" -f `
        $a.tag, $base.prompt_n, $withImg.prompt_n, $imgTok, $withImg.prefill_tps, [math]::Round($withImg.prompt_ms/1000,2), $withImg.decode_tps, $v.board_mib, $v.srv_ded_mib)
    [IO.File]::WriteAllText((Join-Path $script:DATA ("vision-reply-" + $a.tag + ".txt")), $withImg.text, [Text.UTF8Encoding]::new($false))
    Write-Row $out ("  REPLY {0}| {1}" -f $a.tag, ($withImg.text -replace "`r?`n", ' '))
    Stop-Srv
}
Write-Host 'PHASE8 DONE'
