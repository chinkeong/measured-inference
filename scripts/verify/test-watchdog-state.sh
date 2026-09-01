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
