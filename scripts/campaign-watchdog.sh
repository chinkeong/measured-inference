#!/usr/bin/env bash
# The campaign watchdog: GPU state transitions, durability, and stall detection.
#
#   bash scripts/campaign-watchdog.sh <slug> [&]
#   bash scripts/campaign-watchdog.sh <slug> --once      # one report, then exit
#   bash scripts/campaign-watchdog.sh <slug> --stop      # stop the running one
#
# WHY A CAMPAIGN NEEDS ONE. A field-guide campaign is hours to days of detached
# GPU work on a machine that may be borrowed, driven by an agent that is not
# watching. Three things go wrong quietly and this watches for all three:
#
#   THE CARD GOES IDLE AND NOBODY NOTICES. A stage ends, the lock frees, and the
#   next expensive block does not start until someone looks. On a 12-hour plan a
#   30-minute polling interval throws away hours of card time. This emits the
#   moment the card is free, so the next task starts in under a minute.
#
#   COMMITTED WORK NEVER LEAVES THE DISK. Rule 28: a field not written down
#   during the run cannot be recovered at any price -- and a commit that exists
#   only on this disk is not written down anywhere that survives the disk. This
#   pushes whenever HEAD is ahead of origin. It NEVER commits: deciding what is
#   a checkpoint belongs to the campaign, and this only moves what the campaign
#   already decided to keep. `git push` reads refs and does not take the index
#   lock, so it cannot race a concurrent `git add`/`git commit`, and it only
#   ever publishes committed state.
#
#   A JOB HANGS WITHOUT RELEASING THE LOCK. This is the one an idle-trigger
#   cannot see by construction -- the card never goes idle -- so it is caught by
#   watching the heartbeat's mtime instead.
#
# HOW "IDLE" IS DEFINED, AND A WARNING ABOUT IT. Not invented here:
# `gpu_lock.py status` exits 0 only when the lock is free AND no llama.cpp tool
# is live, and AGENTS.md's crash-recovery step names that exact command as the
# is-the-card-idle check. On Linux it is only trustworthy since 2026-09-01:
# /proc/<pid>/comm truncates at 15 characters, so before that fix it printed
# "servers: none" while llama-perplexity held the card. An idle-trigger built on
# the old behaviour fires a FALSE IDLE and launches a second GPU job on top of a
# running one -- the host-exhaustion shape rule 20 exists to prevent. If you
# port this anywhere, port the fix with it.
#
# COVERAGE: SILENCE IS NOT SUCCESS. Every terminal state emits, not just the
# happy one. A watchdog that greps only for "idle" is silent through a
# crashloop, an orphan and a stale lock, and silence reads exactly like "still
# running". Steady BUSY is the only quiet state.
#
# Transition-only: one line when the state CHANGES, never one per poll, so this
# is safe to attach to a notifier that rate-limits.
set -u

SLUG="${1:-}"
MODE="${2:-loop}"
if [ -z "$SLUG" ] || [ "$SLUG" = "-h" ] || [ "$SLUG" = "--help" ]; then
    sed -n '2,50p' "$0" | sed 's/^# \{0,1\}//'
    exit 2
fi

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO" || exit 1

# A PIDFILE, not a pgrep pattern. `pgrep -f campaign-watchdog.sh` matches any
# shell whose command line merely MENTIONS the script -- including the caller
# asking "is it running?", and including this script's own launcher. That
# self-match cost this campaign 26 minutes of idle card on 2026-09-01 when a
# waiter loop waited for itself, and then fooled the gpu_lock hint into staying
# silent. A pid written to a file and checked with kill -0 cannot do that.
PIDFILE="$REPO/results/$SLUG/work/watchdog.pid"
PY="$REPO/.venv/bin/python"; [ -x "$PY" ] || PY="python3"
INTERVAL="${WATCHDOG_INTERVAL:-45}"
PUSH_EVERY="${WATCHDOG_PUSH_EVERY:-300}"     # seconds
STALL_AFTER="${WATCHDOG_STALL_AFTER:-1800}"  # heartbeat older than this = stalled
HB="$REPO/results/$SLUG/work/heartbeat.json"
STATE_F="$REPO/results/$SLUG/data/runner-state.json"

gpu_state() {
    local owner=0 servers idle
    # An "owner" is any campaign job. Matched on the results/<slug>/work/ path so
    # this cannot match ITSELF -- a pgrep pattern that appears in the watcher's
    # own argv makes it wait for itself forever, which is exactly how the first
    # version of this chain hung for 26 minutes on 2026-09-01.
    pgrep -f "results/$SLUG/work/.*\.py" >/dev/null 2>&1 && owner=1
    pgrep -f "scripts/arms\.py" >/dev/null 2>&1 && owner=1
    # bench.py runs from scripts/bench/, not from the campaign's work/ dir, so
    # the path pattern above misses it and a multi-hour benchmark reads as an
    # ORPHAN for its whole duration. Measured 2026-09-01 on the GPQA anchor.
    pgrep -f "scripts/bench/bench\.py" >/dev/null 2>&1 && owner=1
    pgrep -f "scripts/quant-ladder/.*\.py" >/dev/null 2>&1 && owner=1
    servers=$("$PY" scripts/bench/gpu_lock.py status 2>/dev/null | grep -c "LIVE") || servers=0
    if "$PY" scripts/bench/gpu_lock.py status >/dev/null 2>&1; then idle=1; else idle=0; fi
    if   [ "$owner" = 1 ];              then echo "BUSY"
    elif [ "$idle"  = 1 ];              then echo "IDLE"
    elif [ "${servers:-0}" -gt 0 ];     then echo "ORPHAN"
    else                                     echo "HELD-NO-OWNER"; fi
}

stalled() {
    # ACTIVITY, not one task's heartbeat. The first version watched
    # work/heartbeat.json alone, which only runner.py writes -- so it cried
    # STALLED at 1827 s while the ncu profiler was working normally beside it
    # (measured 2026-09-01). A watchdog whose alarm fires on healthy work gets
    # ignored, which is worse than not having one. Newest mtime anywhere the
    # campaign writes is task-agnostic: any task making progress touches
    # something under data/ or work/.
    local newest now age
    newest=$(find "$REPO/results/$SLUG/data" "$REPO/results/$SLUG/work" \
                  -type f -newermt "-${STALL_AFTER} seconds" -print -quit 2>/dev/null)
    [ -n "$newest" ] && return 1          # something moved inside the window
    now=$(date +%s)
    age=$(( now - $(find "$REPO/results/$SLUG/data" "$REPO/results/$SLUG/work" \
             -type f -printf '%T@\n' 2>/dev/null | sort -rn | head -1 | cut -d. -f1) ))
    [ "$age" -gt "$STALL_AFTER" ] && echo "$age" && return 0
    return 1
}

failures() {
    "$PY" -c "
import json,os,sys
p=sys.argv[1]
print(len(json.load(open(p)).get('failed',[])) if os.path.exists(p) else 0)" "$STATE_F" 2>/dev/null || echo 0
}

push_if_ahead() {
    local ahead
    ahead=$(git rev-list --count origin/main..HEAD 2>/dev/null || echo 0)
    if [ "${ahead:-0}" -gt 0 ]; then
        if git push origin main >/dev/null 2>&1; then
            echo "PUSHED $ahead commit(s) to origin/main — $(git log --oneline -1 | cut -c1-60)"
        else
            echo "PUSH FAILED with $ahead commit(s) unpublished — measured data is on this disk only."
        fi
    fi
}

report_once() {
    local s; s=$(gpu_state)
    echo "state=$s  ahead=$(git rev-list --count origin/main..HEAD 2>/dev/null || echo '?')  failures=$(failures)"
    [ -f "$HB" ] && echo "heartbeat: $(cat "$HB" | tr -d '\n' | cut -c1-200)"
}

[ "$MODE" = "--once" ] && { report_once; exit 0; }

if [ "$MODE" = "--stop" ]; then
    if [ -f "$PIDFILE" ] && kill -0 "$(cat "$PIDFILE")" 2>/dev/null; then
        kill "$(cat "$PIDFILE")" && rm -f "$PIDFILE"
        echo "watchdog stopped"
    else
        rm -f "$PIDFILE"; echo "no watchdog running for $SLUG"
    fi
    exit 0
fi

if [ -f "$PIDFILE" ] && kill -0 "$(cat "$PIDFILE")" 2>/dev/null; then
    echo "a watchdog is already running for $SLUG (pid $(cat "$PIDFILE")); --stop it first"
    exit 3
fi
mkdir -p "$(dirname "$PIDFILE")"; echo $$ > "$PIDFILE"
trap 'rm -f "$PIDFILE"' EXIT INT TERM

prev=""; prev_stall=""; orphan_seen=""; last_push=0
while true; do
    state=$(gpu_state)
    fails=$(failures)
    [ "${fails:-0}" -gt 0 ] && state="$state FAILED=$fails"
    # ORPHAN needs to persist before it is believed. Between a job exiting and
    # its server dying there is a ~2 s window where a live llama.cpp tool has no
    # owning process, which is indistinguishable from a real orphan in one poll.
    # Measured 2026-09-01: two false ORPHANs in an hour, both teardown windows.
    # A real orphan does not clear itself, so one poll of patience costs nothing.
    case "$state" in
      ORPHAN*)
        if [ "$orphan_seen" != "yes" ]; then orphan_seen=yes; sleep 5; continue; fi ;;
      *) orphan_seen="" ;;
    esac
    if [ "$state" != "$prev" ]; then
        case "$state" in
          IDLE*)   echo "GPU IDLE — lock free, no llama.cpp tool live. The next campaign task can start now." ;;
          ORPHAN*) echo "GPU ORPHAN — a llama.cpp tool is live with no owning job. Rule 20 hazard: gpu_lock.py status, then kill." ;;
          HELD*)   echo "GPU LOCK HELD by no live process — stale lock. gpu_lock.py release clears it." ;;
          BUSY*)   echo "GPU BUSY — a campaign job holds the card." ;;
        esac
        prev="$state"
    fi
    if age=$(stalled); then
        if [ "$prev_stall" != "yes" ]; then
            echo "STALLED — heartbeat has not moved in ${age}s while state=$state. A job may be hung holding the lock; an idle-trigger cannot see this."
            prev_stall="yes"
        fi
    else
        prev_stall=""
    fi
    now=$(date +%s)
    if [ $(( now - last_push )) -ge "$PUSH_EVERY" ]; then
        out=$(push_if_ahead); [ -n "$out" ] && echo "$out"
        last_push=$now
    fi
    sleep "$INTERVAL"
done
