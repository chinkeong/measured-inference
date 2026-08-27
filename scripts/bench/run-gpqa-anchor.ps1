# The GPQA-Diamond anchor run: the campaign's first comparison against a
# published figure for this model.
#
#   run-gpqa-anchor.ps1 [-Samples 12] [-MaxTokens 30000] [-Effort xhigh] [-Port 1291]
#
# WHY A SCRIPT AND NOT A COMMAND LINE. Two attempts to launch this by hand
# failed on argument quoting, and one of them failed SILENTLY enough to look
# like a running job: PowerShell's -ArgumentList splits a quoted string on its
# spaces, so `--server-args "-ngl 99 -fa on ..."` reached argparse as separate
# tokens and it exited with "expected one argument". The conditions of this run
# also have to be reproducible, and a launcher that records them is the only
# honest way to claim that later.
#
# THE CONDITIONS, and why each is what it is.
#
#   sampler   temperature 1.0, top_p 0.95, top_k 20, presence_penalty 0.0
#             Qwen's THINKING profile, which is what the published 89.2 was
#             produced under. NOT the greedy this campaign uses for speed work.
#             bench.py's built-in default mixes the two profiles - it pairs the
#             thinking temperature with the non-thinking presence penalty of
#             1.5 - so presence_penalty is set explicitly here.
#
#   effort    xhigh, the model card's default and therefore 89.2's condition.
#
#   maxtok    30000 of a 32,768 window. Measured, not guessed: GPQA at xhigh
#             spends 4,247 to over 16,384 output tokens per question on this
#             rig, and a first pilot at a 16,384 cap truncated 3 of 9. bench.py
#             scores a truncated response 0.0, so a tight cap deflates the
#             result through truncation and reports it as model quality.
#
# WHAT THIS RUN CANNOT CLAIM, recorded here so it is not claimed later:
#   - the option shuffle is the mirror's, fixed, and not the order that produced
#     any published number;
#   - the published figure is vendor self-reported, with no independent
#     third-party score for this model on this benchmark;
#   - the rig serves 32,768 tokens against the 262,144 the model supports.
# It detects a BROKEN harness. It does not validate one.
param(
    [int]$Samples = 12,
    [int]$MaxTokens = 30000,
    [string]$Effort = "xhigh",
    [int]$Port = 1291,
    [string]$Model = "C:\Users\chink\.lmstudio\models\unsloth\Qwen3.8-27B-GGUF\Qwen3.8-27B-UD-IQ4_XS.gguf",
    [string]$ServerBin = "E:\AI\llama.cpp\llama-server.exe",
    [string]$Repo = "E:\AI\measured-inference",
    [switch]$Wait
)

$ErrorActionPreference = "Stop"
if (-not (Test-Path $Model))     { throw "model not found: $Model" }
if (-not (Test-Path $ServerBin)) { throw "llama-server not found: $ServerBin" }

$live = Get-Process -Name "llama-server" -ErrorAction SilentlyContinue
if ($live) {
    throw ("llama-server is already running (pid $($live.Id)). This script " +
           "spawns its own server so that bench.py records the server flags " +
           "in the artefact; attaching to someone else's server would record " +
           "an empty server_args and lose the reasoning effort.")
}

$logs = Join-Path $Repo "results\qwen38-27b-blind\logs"
New-Item -ItemType Directory -Force -Path $logs | Out-Null
$stamp = Get-Date -Format "yyyyMMdd_HHmmss"
$log = Join-Path $logs "gpqa-anchor-$stamp.log"

# ONE string, not an array. This is the whole reason the script exists: an
# argument whose value contains spaces cannot survive -ArgumentList as an
# array, and the failure is an argparse error rather than anything obvious.
$serverArgs = "-ngl 99 -fa on -ctk q8_0 -ctv q8_0 --jinja " +
              "--spec-type draft-mtp --spec-draft-n-max 4 --spec-draft-p-min 0.75"

# Reasoning effort goes through the ENVIRONMENT, not the command line.
# --chat-template-kwargs takes a JSON object, and that JSON has to survive
# PowerShell, then cmd.exe, then argparse, then bench.py's plain
# args.server_args.split(), before llama-server ever sees it. It did not: the
# server rejected the value and exited 1. llama.cpp exposes every flag as an
# environment variable for exactly this reason, and an environment variable has
# no quoting layers to cross. It is also the portable form, which matters with
# this toolkit moving to Linux.
$env:LLAMA_ARG_CHAT_TEMPLATE_KWARGS = '{"reasoning_effort":"' + $Effort + '"}'
Write-Output ("effort via env: LLAMA_ARG_CHAT_TEMPLATE_KWARGS=" + $env:LLAMA_ARG_CHAT_TEMPLATE_KWARGS)

$cmd = @(
    "scripts\bench\bench.py",
    "--model", "`"$Model`"",
    "--server-bin", "`"$ServerBin`"",
    "--datasets", "GPQA-Diamond",
    "--samples", "$Samples",
    "--score",
    "--transcripts",
    "--ctx", "32768",
    "--max-tokens", "$MaxTokens",
    "--seed", "42",
    "--presence-penalty", "0.0",
    "--port", "$Port",
    "--server-args", "`"$serverArgs`""
) -join " "

Write-Output "conditions: effort=$Effort  samples=$Samples  max_tokens=$MaxTokens"
Write-Output "sampler   : temperature 1.0, top_p 0.95, top_k 20, presence_penalty 0.0 (vendor thinking profile)"
Write-Output "log       : $log"
Write-Output ""

if ($Wait) {
    & py $cmd.Split(" ", [System.StringSplitOptions]::None) 2>&1 | Tee-Object -FilePath $log
} else {
    # cmd.exe /c keeps the quoting intact through the detach, which
    # Start-Process -ArgumentList as an array does not.
    Start-Process -FilePath "cmd.exe" `
        -ArgumentList "/c", "py $cmd > `"$log`" 2>&1" `
        -WorkingDirectory $Repo -WindowStyle Hidden
    Start-Sleep -Seconds 10
    if (Test-Path $log) {
        $head = Get-Content $log -TotalCount 6
        if ($head -match "error|not found|Traceback") {
            Write-Output "LAUNCH FAILED - first lines of the log:"
            $head | ForEach-Object { Write-Output "  $_" }
            throw "the run did not start; see $log"
        }
        Write-Output "started. follow with: Get-Content -Wait `"$log`""
    } else {
        throw "no log appeared at $log - the process did not start"
    }
}
