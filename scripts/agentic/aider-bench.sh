#!/usr/bin/env bash
# Run aider's OFFICIAL polyglot benchmark against llama-server on the Windows
# host, inside aider's own container.
#
#   aider-bench.sh <run-name> <port> <edit-format> <languages|all> <num-tests|-1>
#
# WHY THE OFFICIAL HARNESS. The public leaderboard measures aider-the-tool
# driving a model - its prompts, its edit formats, its retries. A different
# runner is a different measurement even on identical tasks, and the reason for
# choosing this benchmark was that the rows can sit beside other people's.
#
# WHY THE CONTAINER. The benchmark EXECUTES code the model writes - several
# hundred programs from a quantised model. It also carries the six language
# toolchains, so the host needs no Go, JDK or C++ compiler.
#
# THE GATEWAY IS DISCOVERED, never hardcoded: WSL's address for the Windows
# host changes between restarts.
#
# TWO GUARDS AGAINST A SILENT ZERO, both added 2026-08-26 after a run was
# interrupted and the orphaned container carried on against a dead server:
#
#   1. LIFETIME. The container gets a name and a trap, so interrupting this
#      script stops the container too. Previously killing the launcher left it
#      running - it kept marching through exercises collecting timeouts and
#      would have produced a complete-looking all-zero score.
#
#   2. WATCHDOG. A loop inside the container polls llama-server and ABORTS the
#      run if it disappears. This is the one that matters: a benchmark whose
#      model has gone away does not fail, it silently scores zero on every
#      remaining exercise, and a tidy 0.0 is indistinguishable from a real
#      result. This campaign has been bitten by success-shaped failures three
#      times this week; that is enough to build the check in.
set -u
NAME="${1:-smoke}"
PORT="${2:-1282}"
FMT="${3:-whole}"
LANGS="${4:-python}"
NTESTS="${5:--1}"
CNAME="aiderbench-${NAME}"

cd "$HOME/bench/aider" || exit 1
GW=$(ip route show default | awk '{print $3}')
if [ -z "$GW" ]; then echo "cannot find the Windows host address"; exit 1; fi
BASE="http://${GW}:${PORT}/v1"
echo "llama-server endpoint: $BASE"

code=$(curl -s -m 8 -o /dev/null -w '%{http_code}' "http://${GW}:${PORT}/health")
if [ "$code" != "200" ]; then
  echo "ABORT: llama-server not reachable at ${GW}:${PORT} (HTTP ${code})"
  exit 1
fi
echo "server reachable; container name ${CNAME}"

cleanup() {
  echo ""
  echo "stopping container ${CNAME} (launcher exiting)"
  docker stop "$CNAME" >/dev/null 2>&1
}
trap cleanup EXIT INT TERM

LANGFLAG="--languages $LANGS"
if [ "$LANGS" = "all" ]; then LANGFLAG=""; fi

# The watchdog runs inside the container: two consecutive health failures and
# it kills the benchmark, so the run stops with a visible error instead of
# quietly scoring zero on everything that is left.
INNER='
cd /aider && pip install -q -e . 2>&1 | tail -1
(
  fails=0
  while true; do
    sleep 30
    c=$(curl -s -m 8 -o /dev/null -w "%{http_code}" "$HEALTH_URL" 2>/dev/null)
    if [ "$c" != "200" ]; then
      fails=$((fails+1))
      echo "WATCHDOG: llama-server unreachable (HTTP $c), strike $fails/2"
      if [ "$fails" -ge 2 ]; then
        echo "WATCHDOG: ABORTING - the model is gone, remaining scores would be false zeros"
        pkill -f benchmark.py
        exit 1
      fi
    else
      fails=0
    fi
  done
) &
WD=$!
./benchmark/benchmark.py "$RUN_NAME" --model openai/qwen --edit-format "$EDIT_FMT" \
    $LANG_FLAG --num-tests $NUM_TESTS --threads 1 \
    --exercises-dir polyglot-benchmark --new
rc=$?
kill $WD 2>/dev/null
exit $rc
'

docker run --rm --name "$CNAME" \
  --memory=12g --memory-swap=12g \
  -v "$(pwd)":/aider \
  -v "$(pwd)/tmp.benchmarks/.":/benchmarks \
  -e OPENAI_API_BASE="$BASE" \
  -e OPENAI_API_KEY=local-no-key-needed \
  -e AIDER_BENCHMARK_DIR=/benchmarks \
  -e AIDER_DOCKER=1 \
  -e HEALTH_URL="http://${GW}:${PORT}/health" \
  -e RUN_NAME="$NAME" \
  -e EDIT_FMT="$FMT" \
  -e LANG_FLAG="$LANGFLAG" \
  -e NUM_TESTS="$NTESTS" \
  aider-benchmark \
  bash -c "$INNER"
