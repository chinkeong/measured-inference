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
# is safe to attach to a notifier that rate-limits. The one exception is
# OFF-CARD, which emits a second line if it persists past OFFCARD_WARN -- a
# transition-only log cannot distinguish "downloading, back on the card in two
# minutes" from "wedged in a retry loop for two hours", and those differ by
# hours of card time.
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
OFFCARD_WARN="${WATCHDOG_OFFCARD_WARN:-900}" # card free this long under a live job = say so again
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
    # OWNER ALIVE IS NOT THE SAME AS CARD IN USE, and conflating them blinded
    # this watchdog to the exact window it exists to catch. A campaign task
    # spends long stretches OFF the card -- downloading a multi-GB GGUF,
    # hashing it, converting, scoring transcripts on the CPU. The first version
    # reported BUSY for all of it, because a .py under work/ was alive. Measured
    # 2026-09-01: the GPQA anchor ended at 19:04, the chained task began a
    # 3.5 GB download, and the card sat free with this watchdog silent, while
    # `gpu_lock.py status` had been exiting 0 the whole time. Steady BUSY is the
    # only quiet state, and it had been reporting the wrong one.
    #
    # OFF-CARD is deliberately NOT an invitation to start a second job: rule 20
    # is one GPU job at a time, and the owner is usually about to take the card
    # back. It is an observability state -- it says the card is free, a job is
    # alive, and the clock is running on card time nobody is using.
    if   [ "$owner" = 1 ] && [ "$idle" = 1 ]; then echo "OFF-CARD"
    elif [ "$owner" = 1 ];                    then echo "BUSY"
    elif [ "$idle"  = 1 ];                    then echo "IDLE"
    elif [ "${servers:-0}" -gt 0 ];           then echo "ORPHAN"
    else                                           echo "HELD-NO-OWNER"; fi
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
            # cut -c is BYTE-based in uutils coreutils, which is what this box ships, so
            # slicing a commit subject mid-em-dash emits mojibake into the watchdog's
            # own log. awk substr is character-safe.
            echo "$(date +%H:%M:%S) PUSHED $ahead commit(s) to origin/main - $(git log --oneline -1 | awk '{print substr($0,1,58)}')"
        else
            echo "$(date +%H:%M:%S) PUSH FAILED with $ahead commit(s) unpublished — measured data is on this disk only."
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
    # Stop EVERY instance, not just the one the pidfile happens to name.
    n=$("$PY" - "$SLUG" $$ <<'PYEOF'
import os, signal, sys, time
slug, me = sys.argv[1], {int(sys.argv[2]), os.getpid(), os.getppid()}
n = 0
victims = []
for pid in os.listdir("/proc"):
    if not pid.isdigit() or int(pid) in me:
        continue
    try:
        a = open("/proc/%s/cmdline" % pid, "rb").read().decode("latin-1").split("\x00")
    except Exception:
        continue
    if len(a) >= 3 and a[0].endswith("bash") and a[1].endswith("campaign-watchdog.sh") \
       and a[2] == slug:
        try:
            os.kill(int(pid), signal.SIGTERM); victims.append(int(pid)); n += 1
        except Exception:
            pass

# WAIT FOR THEM TO ACTUALLY DIE. Signalling is not stopping. A watchdog spends
# almost all of its life blocked in `sleep 45`, so SIGTERM lands, the trap runs
# and the process exits a moment later -- and --stop used to return immediately,
# which broke the documented restart recipe two different ways:
#
#   1. `--stop` then start, back to back, refused with "a watchdog is already
#      running" because the victim was still on /proc. The operator's own
#      restart instructions did not work. Measured 2026-09-01.
#   2. Worse and quieter: --stop deleted the PIDFILE itself, BEFORE the victim's
#      EXIT trap ran -- and that trap deletes the pidfile too. Start a new
#      watchdog in that window and the dying one erases the NEW one's pidfile on
#      its way out. The result is a live watchdog that no pidfile names, which
#      is precisely the "FOUR instances live with an EMPTY pidfile" state this
#      file already carries a comment about. The fix for that incident stopped
#      the duplicates; it left the race that manufactures them.
#
# So: wait for every victim to leave /proc, escalate to SIGKILL if one will not,
# and let each victim's own trap remove the pidfile. --stop no longer touches it.
def alive(q):
    """A ZOMBIE IS NOT ALIVE, and os.path.exists("/proc/<pid>") cannot tell.
    A watchdog is nohup'd into the background, so when it exits its parent
    shell has not reaped it yet and it sits in /proc as a zombie -- forever, as
    far as an existence check is concerned. The first version of this wait
    therefore ALWAYS burned its full deadline and ALWAYS finished with SIGKILL:
    measured 2026-09-01, --stop took 15.07 s every time and the process it
    reported "stopped" had in fact been killed, so the EXIT trap never ran.
    Anything later added to that trap would have silently never executed.
    Field 3 of /proc/<pid>/stat is the state; comm (field 2) can contain spaces
    and parentheses, so split after the LAST ')'."""
    try:
        st = open("/proc/%d/stat" % q, "rb").read().decode("latin-1")
    except OSError:
        return False
    try:
        return st.rsplit(")", 1)[1].split()[0] != "Z"
    except IndexError:
        return False

deadline = time.time() + 15
while time.time() < deadline:
    victims = [q for q in victims if alive(q)]
    if not victims:
        break
    time.sleep(0.05)
for q in victims:
    try:
        os.kill(q, signal.SIGKILL)
    except Exception:
        pass
print(n)
PYEOF
)
    # NOT `rm -f "$PIDFILE"` -- see the comment above. Only a victim that never
    # died leaves a stale file, and the start path's /proc scan handles that.
    if [ -f "$PIDFILE" ] && ! kill -0 "$(cat "$PIDFILE" 2>/dev/null)" 2>/dev/null; then
        rm -f "$PIDFILE"
    fi
    echo "stopped $n watchdog(s) for $SLUG"
    exit 0
fi

# A PIDFILE ALONE CANNOT ANSWER "IS ONE ALREADY RUNNING". It names ONE pid, and
# an instance that dies abnormally never runs its EXIT trap, so the file goes
# stale; --stop then clears it, reports "no watchdog running", and the next start
# adds another. Measured 2026-09-01: FOUR instances were live at once with an
# EMPTY pidfile, and the two oldest -- predating the bench.py owner fix -- were
# calling a healthy benchmark an ORPHAN. Contradictory alarms from invisible
# duplicates are worse than no watchdog at all.
#
# So scan /proc for any OTHER process whose argv is literally
# `bash <...>/campaign-watchdog.sh <slug>`. Matching argv POSITIONS cannot
# self-match the way `pgrep -f campaign-watchdog.sh` does, which is the same
# trap that made a waiter wait for itself earlier the same day.
others=$("$PY" - "$SLUG" $$ <<'PYEOF'
import os, sys
slug, me = sys.argv[1], {int(sys.argv[2]), os.getpid(), os.getppid()}
out = []
for pid in os.listdir("/proc"):
    if not pid.isdigit() or int(pid) in me:
        continue
    try:
        a = open("/proc/%s/cmdline" % pid, "rb").read().decode("latin-1").split("\x00")
    except Exception:
        continue
    if len(a) >= 3 and a[0].endswith("bash") and a[1].endswith("campaign-watchdog.sh") \
       and a[2] == slug:
        out.append(pid)
print(" ".join(out))
PYEOF
)
if [ -n "$others" ]; then
    echo "a watchdog is already running for $SLUG (pid$( [ $(echo $others | wc -w) -gt 1 ] && echo s) $others); --stop first"
    exit 3
fi
mkdir -p "$(dirname "$PIDFILE")"; echo $$ > "$PIDFILE"
# The handler must EXIT, not merely clean up. `trap '...' TERM` without an exit
# runs the handler and then RESUMES the script, so SIGTERM told every instance to
# delete its own pidfile and carry on living. Measured 2026-09-01: that turned
# --stop into a no-op, emptied the pidfile, defeated the double-start guard, and
# left FOUR watchdogs running at once -- two of them predating the bench.py owner
# fix and so reporting a healthy benchmark as an ORPHAN. A stop signal that does
# not stop is the worst kind of guard: it reports success and changes nothing.
# The handler also kills the pending sleep: without that, `exit` from a trap
# still waits on the backgrounded child before the shell actually leaves.
trap 'rm -f "$PIDFILE"' EXIT
trap 'rm -f "$PIDFILE"; [ -n "${SLEEP_PID:-}" ] && kill "$SLEEP_PID" 2>/dev/null; exit 0' INT TERM

prev=""; prev_stall=""; orphan_seen=""; last_push=0
offcard_since=0; offcard_warned=""; SLEEP_PID=""
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
          IDLE*)   echo "$(date +%H:%M:%S) GPU IDLE — lock free, no llama.cpp tool live. The next campaign task can start now." ;;
          ORPHAN*) echo "$(date +%H:%M:%S) GPU ORPHAN — a llama.cpp tool is live with no owning job. Rule 20 hazard: gpu_lock.py status, then kill." ;;
          HELD*)   echo "$(date +%H:%M:%S) GPU LOCK HELD by no live process — stale lock. gpu_lock.py release clears it." ;;
          BUSY*)   echo "$(date +%H:%M:%S) GPU BUSY — a campaign job holds the card." ;;
          OFF-CARD*) echo "$(date +%H:%M:%S) GPU OFF-CARD — a campaign job is alive but the card is free (download, hashing, CPU scoring). Do NOT start a second job: rule 20. Card time is being spent doing nothing." ;;
        esac
        prev="$state"
        [ "${state#OFF-CARD}" != "$state" ] && offcard_since=$(date +%s) || offcard_since=0
        offcard_warned=""
    fi
    # A short OFF-CARD is normal; a long one means the job is stuck in its
    # non-GPU phase and the card is idle with nobody watching -- which reads
    # identically to healthy work in a transition-only log. Emit once, then
    # stay quiet, so this cannot become the alarm everyone learns to ignore.
    if [ "${offcard_since:-0}" -gt 0 ] && [ -z "$offcard_warned" ]; then
        if [ $(( $(date +%s) - offcard_since )) -ge "$OFFCARD_WARN" ]; then
            echo "$(date +%H:%M:%S) GPU OFF-CARD for $(( ($(date +%s) - offcard_since) / 60 ))m — the card has been free this whole time while a campaign job runs. Check the job is not wedged in a download or a retry loop."
            offcard_warned=yes
        fi
    fi
    if age=$(stalled); then
        if [ "$prev_stall" != "yes" ]; then
            echo "$(date +%H:%M:%S) STALLED — heartbeat has not moved in ${age}s while state=$state. A job may be hung holding the lock; an idle-trigger cannot see this."
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
    # BACKGROUND SLEEP + wait, NOT a foreground sleep. Bash does not run a trap
    # while a foreground command is executing -- it waits for it to finish. With
    # a plain `sleep 45` the watchdog therefore ignored SIGTERM for up to 45
    # seconds, so --stop's 15 s deadline always expired and every shutdown
    # finished with SIGKILL and no EXIT trap. `wait` IS interruptible by a trap,
    # so this is the difference between a watchdog that stops and one that is
    # killed. Measured 2026-09-01: --stop went from 15.09 s to well under one.
    sleep "$INTERVAL" & SLEEP_PID=$!
    wait "$SLEEP_PID" 2>/dev/null || true
    SLEEP_PID=""
done
