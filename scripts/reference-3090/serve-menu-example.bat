@echo off
rem ============================================================================
rem  serve-qwen.bat - llama.cpp server for Qwen3.8-27B on RTX 3090 24GB
rem ============================================================================
rem  Re-measured 2026-08-22 (full campaign; details in the qwen-27b guide):
rem  - -ngl 99 always (llama.cpp counts the output layer as layer 65; -ngl 64
rem    leaves the vocab projection on CPU: 25.7 vs 39.7 t/s)
rem  - MTP speculation re-swept: n-max 4 + p-min 0.75 is the everyday optimum
rem    (57.9 t/s on real code; speedup is content-dependent, ceiling 119.8)
rem  - UD-IQ4_XS (13.3 GiB): quality tied with Q4_K_M (PPL 6.596 vs 6.535,
rem    GSM8K 93.0 vs 94.0 - both within noise), FASTER everywhere measured,
rem    and text-only it holds the FULL native 262144 context fully resident.
rem    With mmproj its measured resident ceiling is -c 180224.
rem  - Q4_K_M (15.4 GiB): the quality champion by a whisker; +mmproj resident
rem    at -c 122880 (ceiling ~131k).
rem  - reasoning_effort is THE wall-clock knob (xhigh = 4x medium on the same
rem    task); llama-server ignores per-request effort, so set it here.
rem ----------------------------------------------------------------------------
rem  USAGE:  serve-qwen.bat [low^|medium^|xhigh] [context] [1-8]
rem          arg1 = reasoning effort, default xhigh (quality-first)
rem          arg2 = context override (otherwise each choice's safe default)
rem          arg3 = model choice 1-8, skips the menu (for scripts)
rem          No args: menu below, auto-picks [1] after 8 seconds.
rem ----------------------------------------------------------------------------
set EFFORT=%1
if "%EFFORT%"=="" set EFFORT=xhigh
if /i "%EFFORT%"=="low" goto effort_ok
if /i "%EFFORT%"=="medium" goto effort_ok
if /i "%EFFORT%"=="xhigh" goto effort_ok
echo Unknown reasoning effort "%EFFORT%". Usage: serve-qwen.bat [low^|medium^|xhigh] [context] [1-7]
pause
exit /b 1
:effort_ok
set CTXARG=%2
set PICK=%3

set LMS=C:\Users\chink\.lmstudio\models
set MMPROJ=%LMS%\lmstudio-community\Qwen3.8-27B-GGUF\mmproj-Qwen3.8-27B-BF16.gguf

if not "%PICK%"=="" goto pick_%PICK%

echo.
echo  Qwen3.8-27B - pick a model (effort: %EFFORT%):
echo    [1] UD-IQ4_XS   + HI-RES vision  -c 122880  ~55-80 t/s verified, ~3 GB slack (DEFAULT)
echo                                          screenshots to ~4K detail (1080p=2.6k /
echo                                          1440p=4.7k / 4K=10.5k ctx tokens each);
echo                                          full xhigh aquarium cycle + ~10 shots fit
echo    [2] UD-IQ4_XS   text-only  -c 196608  ~55-80 t/s  desktop-safe 196k window
echo    [3] UD-IQ4_XS   text-only  -c 262144  ~26 t/s IF ANYTHING ELSE USES THE GPU
echo                                          (full native - headless/bare desktop only)
echo    [4] Q4_K_M      + vision   -c 122880  ~55-65 t/s  quality champion, reference config
echo    [5] UD-Q4_K_XL  text-only  -c 122880  ~55-65 t/s  quality tied with Q4_K_M, 1 GB bigger:
echo                                          the extra size buys nothing on 24 GB
echo    [6] UD-Q4_K_M   + vision   -c 122880  ~55-65 t/s  measured worse than plain Q4_K_M (PPL +1.8%%)
echo    [7] DFlash2 build                     ~46 t/s on real code (loses to built-in MTP)
echo    [8] NVFP4 HIGH                        ~48-54 t/s  dequant fallback, lower quality
echo.
echo    t/s above = short-context; decode falls with DEPTH: measured ~80 shallow
echo    to ~39 at a 27k-deep prompt (acceptance steady - it is KV reads, not spill)
echo.
choice /C 12345678 /T 8 /D 1 /M "Choice"
goto pick_%ERRORLEVEL%

:pick_1
set MODEL=%LMS%\unsloth\Qwen3.8-27B-GGUF\Qwen3.8-27B-UD-IQ4_XS.gguf
set CTX=122880
set MM=--mmproj "%MMPROJ%" --image-min-tokens 1024 --image-max-tokens 10580
goto launch
:pick_2
set MODEL=%LMS%\unsloth\Qwen3.8-27B-GGUF\Qwen3.8-27B-UD-IQ4_XS.gguf
set CTX=196608
set MM=
goto launch
:pick_3
set MODEL=%LMS%\unsloth\Qwen3.8-27B-GGUF\Qwen3.8-27B-UD-IQ4_XS.gguf
set CTX=262144
set MM=
echo.
echo  WARNING: -c 262144 leaves ~1 GB slack. A browser or agent web UI WILL spill
echo  this to shared memory and decode falls to ~26 t/s (measured). Headless only.
echo.
goto launch
:pick_4
set MODEL=%LMS%\lmstudio-community\Qwen3.8-27B-GGUF\Qwen3.8-27B-Q4_K_M.gguf
set CTX=122880
set MM=--mmproj "%MMPROJ%" --image-min-tokens 1024
goto launch
:pick_5
set MODEL=%LMS%\unsloth\Qwen3.8-27B-GGUF\Qwen3.8-27B-UD-Q4_K_XL.gguf
set CTX=122880
set MM=
goto launch
:pick_6
set MODEL=%LMS%\unsloth\Qwen3.8-27B-GGUF\Qwen3.8-27B-UD-Q4_K_M.gguf
set CTX=122880
set MM=--mmproj "%MMPROJ%" --image-min-tokens 1024
goto launch
:pick_7
call E:\AI\aider\serve-qwen-dflash2.bat %EFFORT%
exit /b
:pick_8
call E:\AI\aider\serve-qwen-nvfp4.bat HIGH %EFFORT%
exit /b

:launch
if not "%CTXARG%"=="" set CTX=%CTXARG%
if not exist "%MODEL%" (
    echo Model not found: %MODEL%
    pause
    exit /b 1
)
if not exist E:\AI\llama.cpp\llama-server.exe (
    echo llama-server.exe not found. Run install-llama-cpp.bat first.
    pause
    exit /b 1
)
echo Serving %MODEL%
echo   effort=%EFFORT%  ctx=%CTX%
E:\AI\llama.cpp\llama-server.exe ^
    -m "%MODEL%" ^
    %MM% ^
    --alias qwen/qwen3.8-27b ^
    -c %CTX% ^
    -ngl 99 ^
    --parallel 1 ^
    --load-mode none ^
    --api-key dummy ^
    -ctk q8_0 -ctv q8_0 ^
    --spec-type draft-mtp --spec-draft-n-max 4 --spec-draft-p-min 0.75 ^
    --temp 1.0 --top-p 0.95 --top-k 20 --min-p 0.0 ^
    --reasoning-preserve ^
    --chat-template-kwargs "{\"reasoning_effort\":\"%EFFORT%\"}" ^
    --jinja ^
    --host 127.0.0.1 ^
    --port 1234
