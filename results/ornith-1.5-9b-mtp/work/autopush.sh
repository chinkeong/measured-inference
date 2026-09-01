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
while true; do
    ahead=$(git rev-list --count origin/main..HEAD 2>/dev/null || echo 0)
    if [ "${ahead:-0}" -gt 0 ]; then
        if out=$(git push origin main 2>&1); then
            echo "[$(date +%H:%M:%S)] pushed $ahead commit(s): $(git log --oneline -1 | cut -c1-72)"
            fails=0
        else
            fails=$((fails + 1))
            echo "[$(date +%H:%M:%S)] push FAILED (attempt $fails): $(echo "$out" | tail -1)"
            # Back off so a broken remote does not spin: 5m, 10m, 20m, capped.
            sleep $(( INTERVAL * (fails < 3 ? fails : 4) ))
            continue
        fi
    fi
    sleep "$INTERVAL"
done
