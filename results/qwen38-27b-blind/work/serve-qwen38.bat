@echo off
rem ---------------------------------------------------------------------------
rem  serve-qwen38.bat - measured menu for Qwen3.8-27B UD-IQ4_XS on an RTX 3090
rem  Every configuration below carries the measurement that justifies it.
rem  Measured 2026-08-23, campaign qwen38-27b-blind. See index.html.
rem  llama.cpp build 10502, commit 0adcc3bb5 (llama-server 0.1.2-dev).
rem
rem  Usage:  serve-qwen38.bat [1|2|3|4] [low|medium|xhigh]
rem          default: 2 medium   (2 is the desktop-safe default)
rem ---------------------------------------------------------------------------
setlocal
set EXE=E:\AI\llama.cpp\llama-server.exe
set MODEL=C:\Users\chink\.lmstudio\models\unsloth\Qwen3.8-27B-GGUF\Qwen3.8-27B-UD-IQ4_XS.gguf
set MMPROJ=C:\Users\chink\.lmstudio\models\lmstudio-community\Qwen3.8-27B-GGUF\mmproj-Qwen3.8-27B-BF16.gguf
set PORT=1234

set CHOICE=%1
if "%CHOICE%"=="" set CHOICE=2
set EFFORT=%2
if "%EFFORT%"=="" set EFFORT=medium

rem Flags that are right on every configuration - see index.html section 03.
set COMMON=-ngl 99 --parallel 1 --load-mode mmap -ctk q8_0 -ctv q8_0 --jinja --reasoning-preserve --host 127.0.0.1 --port %PORT% --alias qwen/qwen3.8-27b

rem Coding drafter: on ANSWER tokens, measured 95.35 t/s writing a JS class
rem vs 42.17 with speculation off (-c 32768, temp 0). Wins every code case.
set SPEC_CODE=--spec-type draft-mtp --spec-draft-n-max 10 --spec-draft-p-min 0.5
rem Prose drafter: on ANSWER tokens, 48.35 t/s writing prose vs 43.80 for
rem SPEC_CODE, and 79.9 % acceptance vs 43.5 %. Wins prose, loses code.
set SPEC_PROSE=--spec-type draft-mtp --spec-draft-n-max 4 --spec-draft-p-min 0.75

if "%CHOICE%"=="1" goto cfg1
if "%CHOICE%"=="2" goto cfg2
if "%CHOICE%"=="3" goto cfg3
if "%CHOICE%"=="4" goto cfg4
goto cfg2

:cfg1
rem [1] CODING + VISION, largest resident window.  BARE DESKTOP ONLY.
rem     MEASURED: llama-server takes 23,316 MiB dedicated, leaving 1,260 MiB
rem     of the 24,576 MiB board for the desktop.  This desktop wanted up to
rem     1,179 MiB on its own, so this config can spill on a busy screen.
rem     Decode 79.3 t/s on a 700-token code probe (reasoning tokens).
echo [1] coding + vision, -c 163840, effort=%EFFORT%
"%EXE%" -m "%MODEL%" --mmproj "%MMPROJ%" --image-min-tokens 1024 -c 163840 %COMMON% %SPEC_CODE% --chat-template-kwargs "{\"reasoning_effort\":\"%EFFORT%\"}"
goto end

:cfg2
rem [2] DEFAULT: CODING + VISION, desktop-safe.  MEASURED: llama-server takes
rem     21,908 MiB, leaving 2,668 MiB - more than twice what this desktop ever
rem     wanted.  Decode 77.1 t/s on a 700-token code probe (reasoning tokens).
echo [2] desktop-safe, -c 131072, effort=%EFFORT%
"%EXE%" -m "%MODEL%" --mmproj "%MMPROJ%" --image-min-tokens 1024 -c 131072 %COMMON% %SPEC_CODE% --chat-template-kwargs "{\"reasoning_effort\":\"%EFFORT%\"}"
goto end

:cfg3
rem [3] TEXT-ONLY, MAXIMUM WINDOW.  Dropping the projector frees a MEASURED
rem     1,138 MiB = ~26,500 tokens of q8_0 window.  MEASURED at -c 180224:
rem     llama-server takes 22,882 MiB, leaving 1,694 MiB.  196,608 leaves 989
rem     and 212,992 leaves 413, with decode already sagging - do not go higher.
echo [3] text-only max window (-c 180224), effort=%EFFORT%
"%EXE%" -m "%MODEL%" -c 180224 %COMMON% %SPEC_CODE% --chat-template-kwargs "{\"reasoning_effort\":\"%EFFORT%\"}"
goto end

:cfg4
rem [4] PROSE / WRITING.  Same window as [2], conservative drafter: MEASURED
rem     on real answer tokens, 48.35 t/s on prose vs 43.80 for the coding
rem     drafter (79.9 % vs 43.5 % acceptance).  Note speculation is worth only
rem     1.16x on prose at all - the floor is 41.55 t/s.
echo [4] prose, -c 131072, effort=%EFFORT%
"%EXE%" -m "%MODEL%" --mmproj "%MMPROJ%" --image-min-tokens 1024 -c 131072 %COMMON% %SPEC_PROSE% --chat-template-kwargs "{\"reasoning_effort\":\"%EFFORT%\"}"
goto end

:end
endlocal
