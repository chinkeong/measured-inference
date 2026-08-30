#!/usr/bin/env bash
#
# sample-power.sh - start / stop / list the detached 500 ms nvidia-smi
# board-power CSV logger. The POSIX twin of sample-power.ps1: the same contract,
# plus one CSV column and seven sidecar keys the .ps1 does not have, each one
# named and justified below.
#
#   bash scripts/power/sample-power.sh start --csv results/<slug>/data/power/campaign-power.csv
#   bash scripts/power/sample-power.sh list
#   bash scripts/power/sample-power.sh stop  --csv results/<slug>/data/power/campaign-power.csv
#   bash scripts/power/sample-power.sh stop  --pid 12345
#   bash scripts/power/sample-power.sh --help
#
# WHY THIS FILE EXISTS
# sample-power.ps1 is the only thing in this repository that STARTS a power
# log; every other file under scripts/power/ is a post-processor. A campaign
# moved to Ubuntu therefore could not do rule 24 energy work at all - no
# logger, no CSV - and scripts/arms.py's power_logging(), which looks for a
# non-empty .csv under results/<slug>/data/power/ carrying a sample newer than
# 300 s and writes power_logging true|false onto every sweep_start line, would
# answer false forever: correctly, permanently, and for want of a starter.
# This file is that starter. It writes the same CSV, in the same place, with
# the .ps1's eleven columns in the same order and one more after them, so
# scripts/power/attribute-power.py joins a Linux log exactly as it joins a
# Windows one.
#
# WHAT IS COPIED EXACTLY, AND WHY EACH ONE MATTERS
#   * The .ps1's eleven --query-gpu fields, IN THAT ORDER, as columns 1-11.
#     attribute-power.py picks the power column by header NAME and re-picks it
#     for every file it opens, so a REORDER under a header is still read off
#     the right column; a RENAME is not - it falls back to column 1 - and
#     neither is a headerless file, which is read positionally. Holding the
#     order fixed is what keeps a Windows CSV and a Linux one safe to merge.
#   * --format=csv,nounits, so the header reads "power.draw [W]" and the values
#     carry no unit suffix - the shape every CSV under results/*/data/power/
#     already has.
#   * -lms 500. Rule 24 requires <= 1 s sampling and the campaign's published
#     numbers were taken at 500 ms; a phase split is only as fine as its
#     samples.
#   * The sidecar <csv>.logger.json and the <csv>.stderr.log beside it: same
#     names, same places, and the .ps1's nine keys under the same spellings, so
#     either platform's stop can read the other's record. The keys are a
#     SUPERSET, not a match - the next section but one says which and why.
#   * The refusals: a logger already writing that CSV, or an existing non-empty
#     CSV, stops a start dead unless --force. Two loggers on one CSV is
#     corruption, not redundancy.
#
# WHAT IS DELIBERATELY NOT COPIED: A TWELFTH COLUMN (rule 28)
# This query carries one field the .ps1's does not - clocks_event_reasons.active
# - appended LAST so columns 1-11 stay identical. Rule 28 names that field:
# "every energy sample therefore carries utilization.memory and
# clocks_event_reasons.active alongside power.draw", because two cards, two
# quantisations or one card at two caps can report the SAME J/token for
# opposite reasons - one starved of bandwidth, one clipped by its power limit -
# and watts alone cannot separate them. The 2026-08-27 audit found seven
# scripts sampling clock, temperature and power only and ruled every J/token
# published to that date unattributable. Widening a query already being issued
# costs nothing, and the field cannot be recovered afterwards at any price.
# THE TWO LOGGERS NOW DIFFER BY THIS COLUMN, AND THAT IS A DEBT, NOT A DESIGN.
# The integrator is unharmed: attribute-power.py resets its column per file and
# finds power.draw by header name (attribute-power.py:106, :115-127), so an
# 11-column Windows CSV and a 12-column Linux one integrate together and either
# may be passed alone. But sample-power.ps1's $script:QUERY must gain the same
# field in the same last position, and until it does, a Windows campaign is
# still taking energy samples rule 28 calls unattributable. The two files move
# together or the divergence is permanent.
#
# THE SIDECAR IS A SUPERSET, NOT A MATCH
# sample-power.ps1 writes nine keys: pid, csv, mode, interval_ms, query,
# started_iso, started_by, tier, verified. This file writes those nine under
# the same spellings and seven more, so a .ps1 stop reading this record finds
# every key it looks for. The seven, and what each is for:
#   gpu_index, gpu_name, driver_version, enforced_power_limit_w
#     rule 3 conditions that move the watts and that the CSV rows do not carry.
#     enforced_power_limit_w above all: a log taken under `nvidia-smi -pl 280`
#     and one taken at this box's stock 350 W are different measurements of the
#     same board, and nothing in the file itself says which you are holding.
#   euid, elevated
#     elevation is a CONDITION of the run (rule 3), recorded and never judged.
#     Reading board power needs none - the watts are identical at euid 0 - but
#     list and stop see a different set of processes at each, so the euid that
#     took the log belongs with the log.
#   stderr_log
#     where nvidia-smi's own complaints went. The .ps1 holds that path in a
#     variable; here it has to outlive the shell that started the logger.
# Read the other way round, a .sh stop given a .ps1 sidecar gets nine keys of
# sixteen and must treat the rest as absent - which it does: "pid" is the only
# key ever read back, and only to report it, never to act on it.
#
# THE TIER - WHAT IS NOT IN THIS NUMBER (rule 24)
# In-band GPU board power (NVML, through nvidia-smi): the graphics board - die,
# VRAM, VRM losses, board fans. PSU conversion loss, the rest of the node (CPU,
# system RAM, drives, chassis fans, the display), idle platform draw and
# datacentre PUE are NOT in it, and are unmeasured on this machine unless a
# wall meter is logged separately. Never call this system power or wall power.
# Label every published figure exactly as the sidecar does:
#     in-band GPU board power (NVML); PSU losses and PUE excluded
#
# ELEVATION - WHICH NUMBERS CHANGE AND WHICH DO NOT
# Running the agent under sudo, or as root, is a supported and deliberate
# choice: it is what buys a fully automated flow, and power registers on other
# tiers only read elevated. It is also a CONDITION of the run (rule 3), so the
# sidecar records the euid that started the logger. What elevation does and
# does not change HERE:
#   * READING board power needs NO elevation. nvidia-smi --query-gpu=power.draw
#     with -lms samples identically at euid 1000 and at euid 0. The watts do
#     not move, so a log started unelevated and a log started under sudo are
#     the same measurement of the same board.
#   * SETTING a board power cap - nvidia-smi -pl <W> - DOES need root, and it
#     moves every watt taken afterwards. This script never sets one. It records
#     the enforced limit in force at start time, so a log taken at a 280 W cap
#     can never be mistaken for one taken at the stock limit.
#   * list and stop SEE MORE when elevated. /proc/<pid>/fd is readable only by
#     the process owner and root, so unelevated you can see another user's
#     nvidia-smi loop but not the file it writes, and stop on it fails EPERM.
#     Your own loggers are fully visible either way.
#   * Other TIERS do need root and are not this file: RAPL (Intel package
#     energy) and powermetrics (Apple) - see reference/platform-notes.md.
#
# WHY STDOUT REDIRECTION AND NOT -f (the one behavioural inversion)
# The .ps1 prefers `-f <csv>` because it puts the destination into nvidia-smi's
# own command line, and falls back to stdout redirection when -f buffers. On
# Linux -f DOES buffer: measured 2026-08-30 on this box (RTX 3090, driver
# 596.36, WSL2 Ubuntu 24.04) a -f logger showed 0 rows after 6 s and dumped all
# 13 at exit, while `stdbuf -oL nvidia-smi ... > csv` showed 7 rows after 3 s
# and 13 after 6 s. A file that only materialises at exit is not a log:
# attribute-power.py cannot integrate a window that has not been written, and
# arms.py's freshness check reads exactly that file's last row and its mtime.
# So the order is inverted here - redirection first, -f only as the fallback -
# and the destination is recovered from /proc/<pid>/fd/1 rather than from the
# command line. Both modes are verified by GROWTH before either is trusted.
#
# THE SAFETY CONTRACT (why stop looks paranoid)
#   * stop NEVER kills by process name. It needs an explicit target - --csv
#     <path> or --pid <n> - and it verifies over /proc that the target really
#     is an nvidia-smi telemetry loop (comm is nvidia-smi, --query-gpu in argv,
#     a loop flag in argv) before it signals anything.
#   * A logger is addressed by the CSV it writes, and the answer comes from the
#     KERNEL, at this instant, every time: a -f / --filename= argument in its
#     command line if it has one (the .ps1's mode, and this script's fallback),
#     otherwise what /proc/<pid>/fd/1 points at. The -f argument is checked
#     FIRST because a -f logger's stdout goes to /dev/null: reading fd/1 first
#     answers a different question truthfully and this one wrongly.
#   * THE SIDECAR'S PID IS NEVER A TARGET. It used to be, and this file used to
#     claim here that re-verifying it meant "a recycled pid can never be hit".
#     That claim was false, and execution falsified it on 2026-08-30 on this
#     box (RTX 3090, driver 596.36, WSL2 Ubuntu 24.04): the re-verification
#     asked only "is this pid a telemetry loop", never "is it writing THIS
#     csv". A stale /tmp/pt/a/other.csv.logger.json naming the live pid of the
#     logger writing /tmp/pt/b/real-b.csv made `stop --csv /tmp/pt/a/other.csv`
#     print "STOP pid=1126 via=sidecar" and "OK stopped 1 logger(s)", and
#     real-b.csv's logger was dead. The same route made `start --csv` refuse a
#     CSV nothing was writing. Pids are recycled and a sidecar outlives the
#     process it names, so that file is a RECORD, not an observation, and this
#     script no longer signals anything on its strength. What it does instead:
#     when stop --csv matches nothing and a sidecar is there, it prints what
#     the record says, what the kernel says that pid is NOW, and the exact
#     `stop --pid <n>` that would act on it. The campaign cost of the old
#     behaviour, which is why it is written down here: a stop aimed at a
#     finished phase ended the live campaign logger, and every sweep after it
#     recorded power_logging: false.
#   * DELIBERATE DIFFERENCE FROM THE .ps1, stated here because the .ps1 states
#     the opposite: on Windows a logger started by hand with shell redirection
#     is invisible to -Stop, because nothing outside the process knows where
#     its stdout went. On Linux the kernel does know, so `stop --csv foo.csv`
#     WILL find and end a hand-started `nvidia-smi ... > foo.csv`. That is the
#     safer half of the trade - it is also what lets start REFUSE a second
#     logger on a CSV a hand-started one already holds - and it is still never
#     by name, and never without the exact path you typed.
#   * SIGTERM first, SIGKILL after 2 s. TERM is enough: measured here, the
#     sampler was gone inside 200 ms.
#
# EXIT CODES
#   0 did what was asked . 2 usage . 3 refused (already logging, a CSV in the
#   way, a target that is not a telemetry loop, or a target that could not be
#   ended) . 4 nvidia-smi missing, or started but no samples appeared within
#   --verify-seconds . 5 stop found nothing to stop
#
# Bash 4+, GNU coreutils, /proc. No Python, no network, nothing installed.
# -e is deliberately OFF: every refusal here has to print its reason and pick
# its own exit code, not die at the first non-zero command.
set -uo pipefail

SCRIPTNAME='sample-power.sh'

# The query. clocks / pstate / util are in here on purpose: they are how you
# prove a low-watt sample was a RAMPING board and not an efficient one, and
# clocks_event_reasons.active is how you prove it was CLIPPED rather than
# merely idle. Columns 1-11 are the .ps1's $script:QUERY byte for byte; column
# 12 is rule 28's required field, appended last and owed back to the .ps1 - see
# "WHAT IS DELIBERATELY NOT COPIED" above.
QUERY='timestamp,power.draw,power.draw.instant,clocks.sm,clocks.mem,utilization.gpu,utilization.memory,memory.used,memory.reserved,temperature.gpu,pstate,clocks_event_reasons.active'

VERB=''
CSV=''
INTERVAL_MS=500
FORCE=0
VERIFY_S=8
TARGET_PID=0
INDEX=''
NVSMI=''
EUID_NOW="$(id -u)"

say() { printf '%s\n' "$*"; }

usage() {
    cat <<'USAGE'
sample-power.sh - start / stop / list the detached nvidia-smi board-power CSV
logger. The POSIX twin of sample-power.ps1: same first eleven columns, same
500 ms period, same <csv>.logger.json sidecar names, same refusals. It logs a
twelfth column the .ps1 does not - clocks_event_reasons.active, which rule 28
requires on every energy sample - and its sidecar carries seven extra keys.

  bash scripts/power/sample-power.sh start --csv results/<slug>/data/power/campaign-power.csv
  bash scripts/power/sample-power.sh list
  bash scripts/power/sample-power.sh stop  --csv results/<slug>/data/power/campaign-power.csv
  bash scripts/power/sample-power.sh stop  --pid 12345

VERBS
  start   launch the detached logger (needs --csv). Survives this shell.
  stop    end the logger writing a CSV (--csv) or one exact pid (--pid).
          Never by process name; the target is verified over /proc first.
  list    show every nvidia-smi telemetry loop on this box. Kills nothing.

OPTIONS
  --csv PATH           output CSV. Required by start, and by stop unless --pid.
                       Put it under results/<slug>/data/power/ - that is the
                       only place scripts/arms.py's power_logging() looks.
  --interval-ms N      sample period, default 500 (rule 24 wants <= 1000).
  --index N            log only GPU N. Default: every GPU, like the .ps1 - on a
                       multi-GPU box that interleaves two boards' rows into one
                       file and attribute-power.py integrates the mixture.
  --force              start: overwrite an existing CSV, or accept a second
                       logger on a CSV another one is already writing.
  --verify-seconds N   start: how long to wait for the CSV to grow, default 8.
  --pid N              stop: end this exact pid, after verifying it is an
                       nvidia-smi telemetry loop. The escape hatch for loggers
                       this script did not start.
  -h, --help           this text. Starts nothing, stops nothing.

THE TIER, on every number this produces: in-band GPU board power (NVML). PSU
losses, the rest of the node and datacentre PUE are NOT in it and stay
unmeasured without a wall meter.

ELEVATION: reading board power needs none - the watts are identical at euid 0
and euid 1000. Setting a cap (nvidia-smi -pl) needs root and moves every watt
afterwards; this script never sets one, it records the enforced limit in the
sidecar. Under sudo, list and stop can also see and end loggers owned by other
users; unelevated they cannot.

Exit: 0 ok . 2 usage . 3 refused or could not end the target . 4 no nvidia-smi
or no samples . 5 nothing to stop
The file header carries the full contract, the buffering measurement behind the
mode order, and the stop safety rules.
USAGE
}

# ---------------------------------------------------------------- primitives

json_esc() { printf '%s' "$1" | sed 's/\\/\\\\/g; s/"/\\"/g'; }

json_str_or_null() {
    if [ -z "$1" ]; then printf 'null'; else printf '"%s"' "$(json_esc "$1")"; fi
}

is_uint() { case "$1" in ''|*[!0-9]*) return 1 ;; *) return 0 ;; esac; }

# Absolutise the path and touch NOTHING. An absolute path is what makes the
# by-path selection below exact - /proc/<pid>/fd/1 always reads back absolute -
# and that is the whole of what stop and list need from a path.
#
# RULE 27: A PROBE MUST NOT PERTURB THE BOX IT MEASURES. There used to be one
# resolver here, the .ps1's Resolve-OutPath one for one, and it ran mkdir -p;
# stop called it. Measured 2026-08-30 on this box: `stop --csv
# /tmp/pt/brandnew/deep/dir/x.csv` printed "NONE no logger found", exited 5,
# and left /tmp/pt/brandnew/deep/dir behind - a verb whose own --help says
# "Kills nothing" creating three directories, on a typo, on the machine the
# numbers are being taken on. A read that writes is not a read. Creating the
# output directory now belongs to start alone, which genuinely needs it.
abs_out_path() {
    local p="$1" dir base d
    dir=$(dirname -- "$p"); base=$(basename -- "$p")
    if d=$(cd -- "$dir" 2>/dev/null && pwd -P); then
        [ "$d" = "/" ] && d=''
        printf '%s/%s' "$d" "$base"
        return 0
    fi
    # The directory is not there, or is unreadable at this euid. Absolutise
    # textually and create nothing: no logger can have fd 1 open inside a
    # directory that does not exist, so the honest answer to "what is writing
    # this path" is "nothing", and it costs the machine no inode to say so.
    case "$p" in
        /*) printf '%s' "$p" ;;
        *)  printf '%s/%s' "$(pwd -P)" "$p" ;;
    esac
}

# start's resolver, and the only thing in this file that puts anything on the
# disk that the measurement did not ask for: the output directory has to exist
# before the redirection in start_logger can open it.
resolve_out_path() {
    local p="$1"
    mkdir -p -- "$(dirname -- "$p")" 2>/dev/null || return 1
    abs_out_path "$p"
}

# Alive means alive, not "has a /proc entry": a logger this shell started and
# then killed stays a zombie until this shell exits, and kill -0 succeeds on a
# zombie. Reporting one as running would make a successful stop look failed.
pid_alive() {
    local st
    [ -d "/proc/$1" ] || return 1
    st=$(awk '/^State:/{print $2; exit}' "/proc/$1/status" 2>/dev/null)
    [ -n "$st" ] && [ "$st" != 'Z' ]
}

cmdline_of() { tr '\0' ' ' < "/proc/$1/cmdline" 2>/dev/null; }

# A logger is a QUERY LOOP. Anything else that happens to be nvidia-smi - a
# one-shot --query-gpu from arms.py sampling VRAM mid-probe, an nvidia-smi -q
# from another tool - is not a logger and is never a target.
is_loop() {
    local comm cl
    comm=$(cat "/proc/$1/comm" 2>/dev/null) || return 1
    [ "$comm" = 'nvidia-smi' ] || return 1
    cl=$(cmdline_of "$1")
    case "$cl" in *--query-gpu*) ;; *) return 1 ;; esac
    case "$cl" in *' -lms '*|*' -l '*|*' --loop-ms'*|*' --loop'*) return 0 ;; esac
    return 1
}

# Where the samples land, asked of the kernel: what is fd 1 open on. This is
# what makes a logger started by hand with `> foo.csv` addressable here, where
# on Windows it is not.
#
# ASKED SECOND, ALWAYS, and the ordering is a bug fix rather than a preference:
# a logger running in -f mode writes the file ITSELF and leaves its stdout
# wherever the launcher put it, which here is /dev/null. Reading fd/1 first
# reported `writes: /dev/null` for a logger that was in fact filling
# /tmp/fallback.csv - a true fact about the process and a false answer to the
# question being asked. An explicit -f in argv is authoritative; fd/1 is the
# answer only when there is no -f.

# The kernel's answer verbatim, or empty when it cannot be read at this euid.
# It exists because dest_fd() below collapses four different truths into one
# empty string, and `list` has to tell them apart - see show_loggers.
fd1_raw() { readlink "/proc/$1/fd/1" 2>/dev/null; }

dest_fd() {
    local d
    d=$(fd1_raw "$1") || return 0
    case "$d" in
        *' (deleted)') return 0 ;;      # the CSV was unlinked under the logger
        /dev/null) return 0 ;;          # a discarded stdout is not a log
        /*) printf '%s' "$d" ;;
    esac
}

# The authoritative route where it exists: -f <path> in the command line, which
# is how the .ps1 starts every logger and how this script's fallback mode does.
# The leading-whitespace requirement is what stops the "-f" inside "--format=".
dest_arg() {
    local cl d
    cl=$(cmdline_of "$1")
    d=$(printf '%s' "$cl" | sed -n 's/.*[[:space:]]-f[[:space:]]\{1,\}\([^ ]\{1,\}\).*/\1/p')
    [ -z "$d" ] && d=$(printf '%s' "$cl" | sed -n 's/.*--filename=\([^ ]\{1,\}\).*/\1/p')
    printf '%s' "$d"
}

all_loops() {
    local p pid
    for p in /proc/[0-9]*; do
        pid=${p#/proc/}
        is_loop "$pid" && printf '%s\n' "$pid"
    done
}

sidecar_path() { printf '%s.logger.json' "$1"; }

# How many live loops this euid can SEE but cannot resolve to a destination.
# Zero means elevation would show nothing new, and saying "rerun under sudo"
# would be a true sentence about /proc offered as a false answer to "why did
# you find nothing" - the defect this file already fixed in list.
n_unreadable_loops() {
    local pid c=0
    for pid in $(all_loops); do
        [ -n "$(dest_arg "$pid")" ] && continue
        [ -n "$(fd1_raw "$pid")" ] && continue
        c=$((c + 1))
    done
    printf '%s' "$c"
}

sidecar_pid() {
    local side="$1"
    [ -f "$side" ] || return 0
    sed -n 's/.*"pid"[[:space:]]*:[[:space:]]*\([0-9]\{1,\}\).*/\1/p' "$side" | head -1
}

# Every logger writing this exact CSV, one "<pid> <via>" per line. Selection is
# by PATH and by nothing else: for each live query loop the kernel is asked,
# now, where that process's samples are going, and only an exact match is
# emitted. Nothing here rests on a file written earlier. A THIRD ROUTE USED TO
# - it added the sidecar's recorded pid on the strength of "that pid is a
# telemetry loop", never asking what it was writing, and it killed the wrong
# logger; the header's SIDECAR'S PID IS NEVER A TARGET has the reproduction.
# What the sidecar records is reported by sidecar_note() and acted on by
# nobody.
loggers_for_csv() {
    local csv="$1" pid d
    for pid in $(all_loops); do
        d=$(dest_arg "$pid")
        if [ -n "$d" ] && [ "$d" = "$csv" ]; then
            printf '%s cmdline\n' "$pid"; continue
        fi
        d=$(dest_fd "$pid")
        if [ -n "$d" ] && [ "$d" = "$csv" ]; then
            printf '%s fd1\n' "$pid"; continue
        fi
    done
}

csv_lines() {
    local n
    [ -f "$1" ] || { printf '%s' 0; return; }
    n=$(wc -l < "$1" 2>/dev/null) || n=0
    printf '%s' "${n:-0}"
}

proc_started() {
    local s
    s=$(ps -o lstart= -p "$1" 2>/dev/null)
    [ -z "$s" ] && s=$(stat -c '%y' "/proc/$1" 2>/dev/null)
    printf '%s' "$(printf '%s' "$s" | awk '{$1=$1; print}')"
}

require_nvidia_smi() {
    NVSMI=$(command -v nvidia-smi 2>/dev/null)
    if [ -n "$NVSMI" ]; then return 0; fi
    say "REFUSED nvidia-smi is not on PATH, so there is no counter to read."
    say "        Ubuntu: the NVIDIA driver package provides it."
    say "        WSL: it ships at /usr/lib/wsl/lib/nvidia-smi - put that on PATH."
    say "        Rule 24: energy is measured or it is absent, and absent is a fact to"
    say "        write down - never a TDP substituted for a reading."
    exit 4
}

# ------------------------------------------------------------------- verbs

# Growth, not existence: a --force append starts from a file that already has
# rows, so the test is n_before + 3 rather than the .ps1's absolute >= 3, which
# is the same test on the fresh file that is the normal case.
verify_growth() {
    local csv="$1" pid="$2" before="$3" i=0 want
    want=$((before + 3))
    while [ "$i" -lt $((VERIFY_S * 2)) ]; do
        sleep 0.5
        i=$((i + 1))
        pid_alive "$pid" || return 1
        [ "$(csv_lines "$csv")" -ge "$want" ] && return 0
    done
    return 1
}

write_sidecar() {
    local side="$1" pid="$2" csv="$3" mode="$4" ok="$5"
    local gpu="$6" driver="$7" limit="$8" err="$9"
    local verified='false' elevated='false'
    [ "$ok" -eq 1 ] && verified='true'
    [ "$EUID_NOW" -eq 0 ] && elevated='true'
    {
        printf '{\n'
        printf '  "pid": %s,\n' "$pid"
        printf '  "csv": "%s",\n' "$(json_esc "$csv")"
        printf '  "mode": "%s",\n' "$mode"
        printf '  "interval_ms": %s,\n' "$INTERVAL_MS"
        printf '  "query": "%s",\n' "$(json_esc "$QUERY")"
        printf '  "started_iso": "%s",\n' "$(date +%Y-%m-%dT%H:%M:%S.%3N)"
        printf '  "started_by": "%s on %s",\n' "$SCRIPTNAME" "$(uname -n)"
        printf '  "tier": "in-band GPU board power (NVML); PSU/wall/PUE excluded",\n'
        printf '  "verified": %s,\n' "$verified"
        printf '  "gpu_index": %s,\n' "$(json_str_or_null "$INDEX")"
        printf '  "gpu_name": %s,\n' "$(json_str_or_null "$gpu")"
        printf '  "driver_version": %s,\n' "$(json_str_or_null "$driver")"
        printf '  "enforced_power_limit_w": %s,\n' "${limit:-null}"
        printf '  "euid": %s,\n' "$EUID_NOW"
        printf '  "elevated": %s,\n' "$elevated"
        printf '  "stderr_log": "%s"\n' "$(json_esc "$err")"
        printf '}\n'
    } > "$side"
}

# TERM, then KILL after 2 s. TERM lets the sampler close its own file, and it
# is enough: measured here, the loop was gone inside 200 ms.
kill_pid() {
    local pid="$1" i=0
    kill -TERM "$pid" 2>/dev/null || return 1
    while [ "$i" -lt 10 ]; do
        sleep 0.2
        i=$((i + 1))
        pid_alive "$pid" || return 0
    done
    kill -KILL "$pid" 2>/dev/null
    sleep 0.3
    pid_alive "$pid" && return 1
    return 0
}

start_logger() {
    local csv="$1" err side hits n_before n_now mode ok pid via append resolved
    local ngpu meta gpu_name driver limit_w
    err="$csv.stderr.log"
    side=$(sidecar_path "$csv")

    hits=$(loggers_for_csv "$csv")
    append=0
    if [ -n "$hits" ]; then
        if [ "$FORCE" -eq 0 ]; then
            say "REFUSED a logger is already writing that CSV:"
            printf '%s\n' "$hits" | while read -r pid via; do
                say "  pid=$pid via=$via started=$(proc_started "$pid")"
            done
            say "  Two loggers appending to one CSV interleave into a file that is no"
            say "  longer a single time series. Use --force to start a second one anyway,"
            say "  or: bash scripts/power/$SCRIPTNAME stop --csv \"$csv\""
            exit 3
        fi
        # --force over a LIVE logger appends rather than truncates: truncating a
        # file another process holds an open offset into leaves a hole of NUL
        # bytes at the front, which is a corrupted log rather than a shared one.
        append=1
        say "WARN  --force: starting a second logger on a CSV another one is writing."
        say "      Appending, not truncating - the live writer's offset would otherwise"
        say "      leave a hole of NULs. Rows from both loggers will interleave here."
    fi

    if [ -s "$csv" ] && [ "$FORCE" -eq 0 ]; then
        say "REFUSED $csv already exists ($(wc -c < "$csv" | tr -d ' ') bytes)."
        say "  One file per phase is the convention - pick a new name, or pass --force."
        exit 3
    fi

    ngpu=$("$NVSMI" -L 2>/dev/null | grep -c '^GPU ')
    if [ -z "$INDEX" ] && [ "${ngpu:-1}" -gt 1 ]; then
        say "WARN  this box reports $ngpu GPUs and no --index was given."
        say "      nvidia-smi then writes one row per GPU per sample into one file, and"
        say "      attribute-power.py integrates whatever rows it finds - two boards"
        say "      summed by accident. Pass --index N unless you mean the mixture."
    fi

    # Rule 3 and rule 28: the conditions that move the watts are read ONCE here,
    # while the run is in front of us, and written into the sidecar. An enforced
    # cap in particular is set by root (nvidia-smi -pl), silently rescales every
    # number in the CSV, and is unrecoverable from the CSV afterwards.
    if [ -n "$INDEX" ]; then
        meta=$("$NVSMI" -i "$INDEX" --query-gpu=name,driver_version,enforced.power.limit \
               --format=csv,noheader,nounits 2>/dev/null | head -1)
    else
        meta=$("$NVSMI" --query-gpu=name,driver_version,enforced.power.limit \
               --format=csv,noheader,nounits 2>/dev/null | head -1)
    fi
    gpu_name=$(printf '%s' "$meta" | awk -F', *' '{print $1}')
    driver=$(printf '%s' "$meta" | awk -F', *' '{print $2}')
    limit_w=$(printf '%s' "$meta" | awk -F', *' '{print $3}')
    case "$limit_w" in ''|*[!0-9.]*) limit_w='' ;; esac

    local QARGS
    QARGS=("--query-gpu=$QUERY" '--format=csv,nounits' '-lms' "$INTERVAL_MS")
    [ -n "$INDEX" ] && QARGS+=('-i' "$INDEX")

    # Prove both files are writable BEFORE launching anything. The failure this
    # catches is an elevation one: a logger started under sudo leaves a
    # root-owned CSV and stderr log behind, and the next unelevated start would
    # otherwise die on a bare "Bad file descriptor" from the redirection below.
    if ! touch -- "$csv" "$err" 2>/dev/null; then
        say "REFUSED cannot write $csv (or $err) as uid $EUID_NOW."
        say "        Files left by an elevated run are owned by root: either rerun"
        say "        elevated, or point --csv at a path this uid owns."
        exit 3
    fi
    # verify_growth counts against the file as the redirect below will LEAVE
    # it, not as it stands now. --force over a live logger appends, so the
    # existing rows survive and the test is n_before + 3; --force over a stale
    # CSV truncates, and asking there for the pre-truncation count + 3 asks for
    # lines that can never arrive. Measured 2026-08-30 before this line
    # existed: a 120-line CSV made `start --force` declare a healthy redirect
    # logger dead after 8 s, kill it, fall back to the -f mode this header
    # proves buffers on Linux, and exit 4 after 18 s - leaving a live logger
    # behind, its CSV at 0 lines and its sidecar reading "verified": false.
    # That is the "a file that materialises only at exit is not a log" state
    # the mode order exists to prevent, reached by the overwrite path.
    if [ "$append" -eq 1 ]; then n_before=$(csv_lines "$csv"); else n_before=0; fi

    # Mode A, redirect: line-buffered stdout into the CSV. First because on
    # Linux this is the mode that actually streams - see the header's
    # measurement. setsid detaches it into its own session, so it outlives this
    # shell, the terminal, and the agent that ran the command.
    local CMD
    CMD=()
    command -v setsid >/dev/null 2>&1 && CMD+=(setsid)
    command -v stdbuf >/dev/null 2>&1 && CMD+=(stdbuf -oL)
    CMD+=("$NVSMI")
    CMD+=("${QARGS[@]}")
    say "START ${CMD[*]} > \"$csv\""
    if [ "$append" -eq 1 ]; then exec 9>>"$csv"; else exec 9>"$csv"; fi
    "${CMD[@]}" >&9 2>>"$err" </dev/null &
    pid=$!
    exec 9>&-
    mode='redirect'

    ok=0
    verify_growth "$csv" "$pid" "$n_before" && ok=1

    if [ "$ok" -eq 0 ]; then
        say "  redirect mode produced no readable growing CSV; falling back to -f."
        kill_pid "$pid" >/dev/null 2>&1
        sleep 0.3
        local CMD2
        CMD2=()
        command -v setsid >/dev/null 2>&1 && CMD2+=(setsid)
        CMD2+=("$NVSMI")
        CMD2+=("${QARGS[@]}")
        CMD2+=('-f' "$csv")
        say "START ${CMD2[*]}"
        "${CMD2[@]}" >/dev/null 2>>"$err" </dev/null &
        pid=$!
        mode='filename'
        verify_growth "$csv" "$pid" "$n_before" && ok=1
    fi

    # The pid to write down is the one ACTUALLY writing this CSV, resolved the
    # same way stop will resolve it - not the one this shell happened to fork.
    # setsid execs in place here so they normally agree; where they do not, the
    # shell's guess is the one that would send stop after the wrong process.
    resolved=$(loggers_for_csv "$csv" | awk 'NR==1{print $1}')
    [ -z "$resolved" ] && resolved="$pid"

    write_sidecar "$side" "$resolved" "$csv" "$mode" "$ok" \
                  "$gpu_name" "$driver" "$limit_w" "$err"

    n_now=$(csv_lines "$csv")
    if [ "$ok" -eq 1 ]; then
        say "OK    pid=$resolved mode=$mode interval=${INTERVAL_MS}ms -> $csv"
        say "      $((n_now - n_before)) line(s) written so far, readable live while it runs."
    else
        say "WARN  pid=$resolved mode=$mode started but no samples were readable within ${VERIFY_S}s."
        say "      Check $err, and that nvidia-smi reads at all:"
        say "      $NVSMI --query-gpu=power.draw --format=csv"
    fi
    say "      sidecar: $side"
    say "      tier   : in-band GPU board power (NVML); PSU losses and PUE excluded."
    if [ -n "$limit_w" ]; then
        say "      cap    : ${limit_w} W enforced at start (nvidia-smi -pl, root-only, changes every watt below)."
    fi
    say "      NOTE clock-ramp: the first samples after an idle board read LOW because the"
    say "      SM clock is still ramping (measured here: ~900-990 MHz vs 1455 settled). Warm"
    say "      the GPU with a throwaway request before any arm you intend to publish."
    case "$csv" in
        */results/*/data/power/*.csv) ;;
        *)  say "      WARN this path is not results/<slug>/data/power/*.csv, which is the only"
            say "      place scripts/arms.py's power_logging() looks. A sweep started now would"
            say "      write power_logging: false while this logger runs - and rule 28 says a"
            say "      field not written during the run cannot be recovered afterwards." ;;
    esac
    say "      stop with: bash scripts/power/$SCRIPTNAME stop --csv \"$csv\""
    [ "$ok" -eq 1 ] || exit 4
    exit 0
}

# What the sidecar SAYS, and what the kernel says that pid is NOW. Printed
# when stop --csv found nothing, and never acted on: a sidecar outlives the
# process it names and pids are recycled, so this file is a record of what was
# started, not evidence of what is running. Naming the divergence is the useful
# half - it is how an operator learns the logger already ended, or that the
# record is stale, without this script guessing on their behalf.
sidecar_note() {
    local side spid d
    side=$(sidecar_path "$1")
    [ -f "$side" ] || return 0
    spid=$(sidecar_pid "$side")
    say ""
    say "      A sidecar is beside that path: $side"
    if [ -z "$spid" ]; then
        say "      It records no pid, so it names nothing to stop."
        return 0
    fi
    if ! pid_alive "$spid"; then
        say "      It records pid $spid, which is not running: that logger has already"
        say "      ended and the record outlived it. The CSV, if any, is complete."
        return 0
    fi
    if ! is_loop "$spid"; then
        say "      It records pid $spid, which IS running and is NOT an nvidia-smi"
        say "      telemetry loop - the pid was recycled onto something else. Nothing"
        say "      was signalled. That process is: $(cmdline_of "$spid")"
        return 0
    fi
    d=$(dest_arg "$spid"); [ -z "$d" ] && d=$(fd1_raw "$spid")
    if [ -z "$d" ]; then
        # The one case where "it is not writing this CSV" would be a guess.
        say "      It records pid $spid, which IS a live telemetry loop, and this euid"
        say "      cannot read /proc/$spid/fd/1 - so whether it is writing this CSV is"
        say "      UNKNOWN here, not answered. Rerun elevated to find out, or end it"
        say "      deliberately: bash scripts/power/$SCRIPTNAME stop --pid $spid"
        return 0
    fi
    say "      It records pid $spid, which is a live telemetry loop writing"
    say "      $d - not this CSV."
    say "      It was NOT stopped: stop --csv ends only what the kernel says is"
    say "      writing the path you typed. To end that one anyway, on purpose:"
    say "        bash scripts/power/$SCRIPTNAME stop --pid $spid"
}

stop_by_csv() {
    local csv="$1" hits n=0 pid via side hidden
    hits=$(loggers_for_csv "$csv")
    if [ -z "$hits" ]; then
        say "NONE  no logger found writing $csv"
        say "      Nothing was killed. list shows every nvidia-smi telemetry loop on this"
        say "      box with the file each one writes; stop --pid <pid> ends one by hand."
        hidden=$(n_unreadable_loops)
        if [ "$EUID_NOW" -ne 0 ] && [ "$hidden" -gt 0 ]; then
            say "      $hidden telemetry loop(s) on this box could not be resolved to a file at"
            say "      euid $EUID_NOW - /proc/<pid>/fd is owner-and-root-only, so one of them may"
            say "      be writing this CSV. Rerun elevated to find out. (This line is printed"
            say "      only when such a loop exists; it is not a stock excuse.)"
        fi
        sidecar_note "$csv"
        exit 5
    fi
    while read -r pid via; do
        [ -z "$pid" ] && continue
        say "STOP  pid=$pid via=$via started=$(proc_started "$pid")"
        if kill_pid "$pid"; then
            n=$((n + 1))
        else
            say "  FAILED could not end pid $pid."
            [ "$EUID_NOW" -ne 0 ] && say "         It may not be owned by this uid - rerun under sudo."
        fi
    done <<EOF
$hits
EOF
    # The sidecar is the record of a RUNNING logger, so it goes only when one
    # actually stopped. Deleting it after a failed kill would hide the live
    # logger from the next stop - and unelevated, deleting a root-owned sidecar
    # fails anyway; that EPERM is not news to anyone and is not printed.
    if [ "$n" -gt 0 ]; then
        side=$(sidecar_path "$csv")
        [ -f "$side" ] && rm -f -- "$side" 2>/dev/null
        say "OK    stopped $n logger(s); CSV left in place: $csv"
        exit 0
    fi
    say "FAILED  found the logger(s) writing $csv and ended none of them."
    say "        The CSV is untouched and still being written."
    [ "$EUID_NOW" -ne 0 ] && say "        Unelevated: a logger started under sudo is stopped under sudo."
    exit 3
}

stop_by_pid() {
    local pid="$1"
    if ! is_loop "$pid"; then
        say "REFUSED pid $pid is not a running nvidia-smi telemetry loop. Nothing killed."
        say "        (comm must be nvidia-smi, with --query-gpu and a loop flag in argv.)"
        exit 3
    fi
    say "STOP  pid=$pid (explicit) started=$(proc_started "$pid")"
    say "      $(cmdline_of "$pid")"
    if kill_pid "$pid"; then
        say "OK    stopped 1 logger."
        exit 0
    fi
    say "  FAILED could not end pid $pid."
    [ "$EUID_NOW" -ne 0 ] && say "        It may not be owned by this uid - rerun under sudo."
    exit 3
}

# Four different truths, four different sentences. dest_fd() returns empty for
# all four because its question is "which CSV", and for three of them the
# answer is "none"; list's question is "what is this process doing", and those
# three have real answers. Reported as one line - "(not resolvable at euid N -
# /proc/N/fd is owner-and-root-only)" - it was a true fact about SOME process
# standing in for a false answer about this one: measured 2026-08-30 at euid
# 1000 against three loops whose /proc/<pid>/fd was fully readable, whose fd 1
# was /dev/null, an unlinked CSV and a pipe, and for which rerunning under sudo
# would have changed nothing at all.
show_loggers() {
    local pid d raw unresolved=0 any=0
    for pid in $(all_loops); do
        any=1
        d=$(dest_arg "$pid")
        if [ -z "$d" ]; then
            raw=$(fd1_raw "$pid")
            if [ -z "$raw" ]; then
                d="(fd 1 not readable at euid $EUID_NOW: /proc/$pid/fd is"
                d="$d owner-and-root-only, so this one is another user's - elevate to see it)"
                unresolved=1
            else
                case "$raw" in
                    *' (deleted)')
                        d="${raw% (deleted)}  <- UNLINKED while open: the rows are going to"
                        d="$d an inode with no name and nothing will ever read them back" ;;
                    /dev/null)
                        d="/dev/null  <- stdout discarded: this loop is recording nothing,"
                        d="$d and elevation would not change that" ;;
                    /*) d="$raw" ;;
                    *)  d="$raw  <- not a file, so no CSV is being written here" ;;
                esac
            fi
        fi
        say ""
        say "  pid     : $pid"
        say "  started : $(proc_started "$pid")"
        say "  writes  : $d"
        say "  cmdline : $(cmdline_of "$pid")"
    done
    if [ "$any" -eq 0 ]; then
        say "no nvidia-smi telemetry loops running"
        say "(rule 24: with none running, a sweep started now records timings and no"
        say " watts, and arms.py writes power_logging: false on its sweep_start line.)"
        exit 0
    fi
    say ""
    say "Stop one with:  stop --csv <its csv>   (path-addressed, verified)"
    say "            or: stop --pid <pid>       (explicit, verified, never by name)"
    if [ "$unresolved" -eq 1 ]; then
        say "One or more fd 1 links could not be READ at euid $EUID_NOW - those loops belong"
        say "to another user; rerun elevated to resolve them. Every other line above is the"
        say "kernel's own answer and elevation does not change it."
    fi
    exit 0
}

# ----------------------------------------------------------------- dispatch

while [ $# -gt 0 ]; do
    case "$1" in
        -h|--help|help)     usage; exit 0 ;;
        start|stop|list)    VERB="$1" ;;
        --csv)              CSV="${2:-}"; shift ;;
        --csv=*)            CSV="${1#*=}" ;;
        --interval-ms)      INTERVAL_MS="${2:-}"; shift ;;
        --interval-ms=*)    INTERVAL_MS="${1#*=}" ;;
        --verify-seconds)   VERIFY_S="${2:-}"; shift ;;
        --verify-seconds=*) VERIFY_S="${1#*=}" ;;
        --index)            INDEX="${2:-}"; shift ;;
        --index=*)          INDEX="${1#*=}" ;;
        --pid)              TARGET_PID="${2:-}"; shift ;;
        --pid=*)            TARGET_PID="${1#*=}" ;;
        --force)            FORCE=1 ;;
        *) say "REFUSED unknown argument: $1"
           say "        try: bash scripts/power/$SCRIPTNAME --help"
           exit 2 ;;
    esac
    shift
done

if ! is_uint "$INTERVAL_MS" || [ "$INTERVAL_MS" -le 0 ]; then
    say "REFUSED --interval-ms must be a positive integer (got '$INTERVAL_MS')."
    exit 2
fi
if ! is_uint "$VERIFY_S"; then
    say "REFUSED --verify-seconds must be a non-negative integer (got '$VERIFY_S')."
    exit 2
fi
if [ -n "$INDEX" ] && ! is_uint "$INDEX"; then
    say "REFUSED --index must be a GPU index (got '$INDEX')."
    exit 2
fi
if ! is_uint "$TARGET_PID"; then
    say "REFUSED --pid must be a pid (got '$TARGET_PID')."
    exit 2
fi
if [ "$INTERVAL_MS" -gt 1000 ]; then
    say "WARN  --interval-ms $INTERVAL_MS is coarser than rule 24's 1000 ms ceiling;"
    say "      a prefill window may hold too few samples to integrate."
fi

# Every route to a logger here - is it one, what is it writing, is it still
# alive - goes through /proc. Without it this script can see nothing, and
# guessing by process name is exactly what the safety contract forbids.
[ -d /proc ] || { say "REFUSED /proc is not mounted; this script cannot see processes without it."; exit 2; }

case "$VERB" in
    list)
        show_loggers
        ;;
    stop)
        if [ "$TARGET_PID" -gt 0 ]; then stop_by_pid "$TARGET_PID"; fi
        if [ -z "$CSV" ]; then
            say "REFUSED stop needs an explicit target: --csv <path> or --pid <n>."
            say "        This script will not stop loggers by process name."
            exit 2
        fi
        # abs_out_path, not resolve_out_path: rule 27, a stop creates nothing.
        stop_by_csv "$(abs_out_path "$CSV")"
        ;;
    start)
        if [ -z "$CSV" ]; then
            say "REFUSED start needs --csv <path>."
            say "        e.g. bash scripts/power/$SCRIPTNAME start --csv results/<slug>/data/power/campaign-power.csv"
            exit 2
        fi
        require_nvidia_smi
        FULL=$(resolve_out_path "$CSV") || {
            say "REFUSED could not create the directory for $CSV"; exit 2; }
        start_logger "$FULL"
        ;;
    *)
        # No verb starts nothing. The .ps1 defaults to -Start because a
        # PowerShell parameter set has to have a default; a bare
        # sample-power.sh that silently launched a logger would change the
        # machine a measurement is being taken on, on the strength of a typo.
        say "REFUSED no verb. Say start, stop or list."
        say "        bash scripts/power/$SCRIPTNAME --help"
        exit 2
        ;;
esac
