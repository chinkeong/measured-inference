#!/usr/bin/env bash
# Drive campaign-watchdog.sh's gpu_state() through every machine state.
#
# WHY THIS IS A TEST AND NOT AN EYEBALL. The defect this pins down was invisible
# in live checking for a stupid reason: the machine kept changing state while it
# was being looked at. On 2026-09-01 the old and new implementations were run
# back to back against a card that had been free for ten minutes, and both
# printed BUSY -- because in the seconds between the two runs the campaign task
# finished its download and legitimately took the card. A state machine has to
# be driven, not observed.
#
# gpu_state() reads exactly two things: whether a campaign process is alive
# (pgrep) and what `gpu_lock.py status` says (exit code + "LIVE" lines). Both
# are stubbed here, so all five states are reachable in a second with no GPU.
set -u
cd "$(dirname "${BASH_SOURCE[0]}")/.." || exit 1
REPO="$(cd .. && pwd)"
WD="${WATCHDOG_UNDER_TEST:-$REPO/scripts/campaign-watchdog.sh}"

# Lift gpu_state() out of the script rather than re-stating it: a test that
# carries its own copy of the logic passes while the real one is broken.
eval "$(sed -n '/^gpu_state() {/,/^}/p' "$WD")"

SLUG="test-slug"        # gpu_state builds its pgrep patterns from this
STUB=$(mktemp); trap 'rm -f "$STUB"' EXIT
PY="$STUB"

drive() {  # <owner> <lock_exit> <n_live> <expected>
    # STUB_OWNER, not `owner`. Bash scoping is DYNAMIC: gpu_state() declares
    # `local owner=0`, so a stub that read a variable called `owner` saw
    # gpu_state's own local rather than this function's, always returned
    # not-found, and made every owner=1 row silently test owner=0 instead. The
    # first run of this file "failed" two rows for that reason and not for the
    # reason under test. A stub must not share a name with anything in the code
    # it stands in for.
    local code="$2" live="$3" want="$4" got
    STUB_OWNER="$1"
    pgrep() { [ "$STUB_OWNER" = 1 ]; }
    { echo '#!/bin/sh'
      for _ in $(seq 1 "$live"); do echo 'echo "servers: 1 LIVE - llama-perplexity(1)"'; done
      echo "exit $code"; } > "$STUB"
    chmod +x "$STUB"
    got=$(gpu_state)
    if [ "$got" = "$want" ]; then
        printf '  ok    owner=%s lock_exit=%s live=%s -> %s\n' "$STUB_OWNER" "$code" "$live" "$got"
    else
        printf '  FAIL  owner=%s lock_exit=%s live=%s -> %s (wanted %s)\n' "$STUB_OWNER" "$code" "$live" "$got" "$want"
        FAILED=$((FAILED + 1))
    fi
}

FAILED=0

# ---------------------------------------------------------------- stalled()
# stalled() is the ONLY detector for the failure the watchdog's own header
# calls "the one an idle-trigger cannot see by construction" -- a job wedged
# while still holding the lock, where gpu_state() reports a steady BUSY and
# BUSY is the documented quiet state. It had no test. It was also blind: it
# asked "has anything under data/ or work/ changed", and the watchdog's own
# log, the autopush log and the 500 ms power CSV all live there, so its own
# output kept resetting its own alarm.
eval "$(sed -n '/^_campaign_writes() {/,/^}/p' "$WD")"
eval "$(sed -n '/^stalled() {/,/^}/p' "$WD")"

REPO_REAL="$REPO"
TREE=$(mktemp -d); trap 'rm -f "$STUB"; rm -rf "$TREE"' EXIT
STALL_AFTER=1800

stall_case() {  # <description> <fresh-file-or-none> <expect: STALLED|running>
    local desc="$1" fresh="$2" want="$3" verdict
    rm -rf "$TREE/results/$SLUG"
    mkdir -p "$TREE/results/$SLUG/data/power" "$TREE/results/$SLUG/work"
    : > "$TREE/results/$SLUG/data/kld.json"          # the campaign's real output
    touch -d "-3 hours" "$TREE/results/$SLUG/data/kld.json"
    if [ "$fresh" != "none" ]; then
        : > "$TREE/results/$SLUG/$fresh"             # touched NOW
    fi
    REPO="$TREE"
    if stalled >/dev/null; then verdict=STALLED; else verdict=running; fi
    if [ "$verdict" = "$want" ]; then
        printf '  ok    %-46s -> %s
' "$desc" "$verdict"
    else
        printf '  FAIL  %-46s -> %s (wanted %s)
' "$desc" "$verdict" "$want"
        FAILED=$((FAILED + 1))
    fi
}

echo "stalled() -- campaign silent 3 h, STALL_AFTER=1800:"
stall_case "campaign wrote recently"          "data/ppl.json"      running
stall_case "only the watchdog's own log moved" "work/watchdog.log"  STALLED
stall_case "only the autopush log moved"       "work/autopush.log"  STALLED
stall_case "only the 500ms power CSV moved"    "data/power/p.csv"   STALLED
stall_case "nothing moved at all"              "none"               STALLED
REPO="$REPO_REAL"
echo

# ------------------------------------------------------------ power_health()
# Rule 24 had no supervisor: the logger is started once and never re-checked.
# On 2026-09-01 it appended ~18 h to an inode with no name and every consumer
# still read power_logging: true.
eval "$(sed -n '/^power_health() {/,/^}/p' "$WD")"

power_case() {  # <description> <readlink-output|NONE> <expected>
    local desc="$1" want="$3" got
    STUB_LINK="$2"
    if [ "$STUB_LINK" = "NONE" ]; then
        pgrep() { return 1; }
    else
        pgrep() { echo 4242; }
    fi
    readlink() { [ "$STUB_LINK" = "NONE" ] && return 1; echo "$STUB_LINK"; }
    got=$(power_health) || got="healthy"
    if [ "$got" = "$want" ]; then
        printf '  ok    %-46s -> %s
' "$desc" "$got"
    else
        printf '  FAIL  %-46s -> %s (wanted %s)
' "$desc" "$got" "$want"
        FAILED=$((FAILED + 1))
    fi
}

echo "power_health():"
power_case "logging to a linked file"   "/r/results/$SLUG/data/power/c.csv"           healthy
power_case "logging to an UNLINKED file" "/r/results/$SLUG/data/power/c.csv (deleted)" "UNLINKED 4242"
power_case "no logger running at all"    NONE                                          ABSENT
unset -f pgrep readlink
echo

echo "gpu_state() decision table:"
# The regression this file exists for: a campaign job alive while the card is
# free. Downloading a multi-GB GGUF, hashing, converting, CPU scoring. Reported
# BUSY for the entire window the watchdog exists to catch.
drive 1 0 0 OFF-CARD
drive 1 1 1 BUSY            # job holds the card: the genuinely quiet state
drive 0 0 0 IDLE            # nothing running, card free: next task may start
drive 0 1 1 ORPHAN          # a llama.cpp tool with no owning job (rule 20 hazard)
drive 0 1 0 HELD-NO-OWNER   # stale lock, no process behind it
echo
[ "$FAILED" = 0 ] && { echo "PASS"; exit 0; } || { echo "$FAILED FAILED"; exit 1; }
