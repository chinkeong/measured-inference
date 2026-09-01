#!/usr/bin/env bash
# Auto-push loop: keep origin/main within one interval of local HEAD.
#
# WHY THIS EXISTS. This campaign checkpoint-commits after every task, which
# protects against a crash but not against losing the machine: a borrowed or
# rented box can vanish with every commit still local. The measurements are the
# scarce thing (rule 28 -- a field not written down during the run cannot be
# recovered at any price), and a commit that only exists on this disk is not
# written down anywhere that survives the disk.
#
# SAFE ALONGSIDE THE RUNNER. `git push` reads refs and does NOT take the index
# lock, so it cannot race the runner's `git add`/`git commit`. It also only ever
# publishes committed state -- a half-written JSON in the working tree is not
# pushed, by construction.
#
# It never commits. Deciding what is a checkpoint is the runner's job and the
# orchestrator's; this only moves what they already decided to keep.
set -u
REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
INTERVAL="${AUTOPUSH_INTERVAL:-300}"
cd "$REPO" || exit 1
fails=0
last_beat=0
BEAT="${AUTOPUSH_HEARTBEAT:-3600}"     # say "still alive, nothing to push" this often
while true; do
    # THE COUNT AND THE PUSH MUST NAME THE SAME REF. This counted
    # `origin/main..HEAD` and pushed the `main` ref: from any branch that is not
    # main it reported "pushed 3 commit(s)" while git said "Everything
    # up-to-date" and exited 0, so the failure branch never ran and measured
    # data stayed on this disk under a line claiming it had left (rule 28).
    branch=$(git rev-parse --abbrev-ref HEAD 2>/dev/null) || branch=""
    now=$(date +%s)
    if [ -z "$branch" ] || [ "$branch" = "HEAD" ]; then
        echo "[$(date +%H:%M:%S)] BLOCKED: detached HEAD, no branch to publish"
        sleep "$INTERVAL"; continue
    fi
    if git rev-parse --verify --quiet "origin/$branch" >/dev/null 2>&1; then
        ahead=$(git rev-list --count "origin/$branch..HEAD" 2>/dev/null) || ahead=""
    else
        ahead=""      # UNKNOWN. `|| echo 0` used to make this read as "nothing
                      # to push", a silent permanent no-op: the loop stayed
                      # alive, logged nothing and published nothing for as long
                      # as the remote ref stayed missing.
    fi
    if [ -n "$ahead" ] && [ "$ahead" = "0" ]; then
        # A SILENT LOOP AND A DEAD LOOP LOOK IDENTICAL IN A LOG. This printed
        # nothing on a quiet iteration, so eight hours of "nothing to push" and
        # eight hours of "the process died" were byte-identical to anyone
        # reading autopush.log. A heartbeat costs one line an hour and makes the
        # difference visible.
        if [ $(( now - last_beat )) -ge "$BEAT" ]; then
            echo "[$(date +%H:%M:%S)] alive, nothing to push (origin/$branch is current)"
            last_beat=$now
        fi
        sleep "$INTERVAL"; continue
    fi
    if out=$(git push origin "$branch" 2>&1); then
        left=$(git rev-list --count "origin/$branch..HEAD" 2>/dev/null || echo "?")
        if [ "$left" = "0" ]; then
            echo "[$(date +%H:%M:%S)] pushed ${ahead:-?} commit(s) to origin/$branch, verified 0 remaining: $(git log --oneline -1 | awk '{print substr($0,1,72)}')"
            fails=0
            last_beat=$now
        else
            # A zero exit is not proof anything landed.
            echo "[$(date +%H:%M:%S)] INCOMPLETE: git exited 0 but $left commit(s) remain unpublished on origin/$branch"
            fails=$((fails + 1))
        fi
    else
        # A LOST RACE IS NOT A LOST COMMIT: this loop, the campaign watchdog and
        # runner.py's commit() all push the same ref, so collisions are routine
        # and the loser exits non-zero over data that already landed.
        left=$(git rev-list --count "origin/$branch..HEAD" 2>/dev/null || echo "?")
        if [ "$left" = "0" ]; then
            echo "[$(date +%H:%M:%S)] lost a push race but origin/$branch already has everything - not an error"
            fails=0
            last_beat=$now
            sleep "$INTERVAL"; continue
        fi
        fails=$((fails + 1))
        # Keep the REASON, not just its last line: a non-fast-forward, an
        # over-limit file and an expired credential are permanent and need
        # acting on; a DNS blip is not. The old log could not tell them apart.
        echo "[$(date +%H:%M:%S)] push FAILED (attempt $fails): $(printf '%s' "$out" | tr '\n' ' ' | awk '{print substr($0,1,200)}')"
        # 5m, 10m, 20m, capped. `fails` resets only on a VERIFIED push, so the
        # backoff ratchets while the remote is broken -- deliberate: a doomed
        # push retried every 5 minutes buries every other line in this log.
        sleep $(( INTERVAL * (fails < 3 ? fails : 4) ))
        continue
    fi
    sleep "$INTERVAL"
done
