#!/usr/bin/env bash
# Launch the polyglot benchmark DETACHED and return immediately.
#
#   aider-bench-detached.sh <run-name> <port> <edit-format> <languages|all> <num-tests|-1>
#
# WHY DETACHED, and this is not a preference. Two full runs died on 2026-08-26
# minutes after launch, both times taking the llama-server and the benchmark
# together, both times while the run was demonstrably healthy - the second had
# scored 489 lines of exercises before it stopped. The common factor was that
# this session HELD both processes open. So it no longer does: the model is
# started with Start-Process on Windows and the benchmark with `docker run -d`,
# which means Windows and Docker own their lifetimes and nothing here has to
# stay alive for four hours.
#
# The watchdog inside the container matters MORE in this mode, not less. With
# nothing holding the container, a model that disappears would otherwise leave
# it collecting timeouts through every remaining exercise and reporting a tidy,
# complete-looking all-zero score. That guard was verified twice on 2026-08-26,
# once staged and once for real: when the run above was killed, the container
# was orphaned with no launcher left, and it still shut itself down in 24
# seconds.
#
# Poll it with:   docker logs -f aiderbench-<run-name>
# Results land in ~/bench/aider/tmp.benchmarks/<date>--<run-name>/
set -u
NAME="${1:-run}"
PORT="${2:-1283}"
FMT="${3:-whole}"
LANGS="${4:-all}"
NTESTS="${5:--1}"
CNAME="aiderbench-${NAME}"

cd "$HOME/bench/aider" || exit 1
GW=$(ip route show default | awk '{print $3}')
[ -z "$GW" ] && { echo "cannot find the Windows host address"; exit 1; }

# Pre-flight: refuse to start against a server that is not READY. Anything
# other than 200 counts - a server still loading a model answers HTTP 503, and
# a benchmark that starts then scores zeros on its first exercises and never
# says why. This fired for real on 2026-08-26.
code=$(curl -s -m 8 -o /dev/null -w '%{http_code}' "http://${GW}:${PORT}/health")
[ "$code" != "200" ] && { echo "ABORT: llama-server not ready at ${GW}:${PORT} (HTTP ${code})"; exit 1; }

docker rm -f "$CNAME" >/dev/null 2>&1

LANGFLAG="--languages $LANGS"
[ "$LANGS" = "all" ] && LANGFLAG=""

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
echo "BENCHMARK FINISHED rc=$rc"
exit $rc
'

# ATTACHED, but launched with setsid so nothing in the calling session owns it.
#
# `docker run -d` DOES NOT WORK HERE and the difference is not subtle: measured
# 2026-08-26, detached completed ONE exercise in 80 minutes while attached
# completed TWO in 40 seconds, same image, same model, same flags, same
# language. Something has to keep draining the container's output; with -d
# nothing does and the run wedges after the first exercise.
#
# So the container stays attached to a setsid'd shell that redirects its output
# to a file. That shell survives this session ending, which was the original
# reason for wanting -d, without taking the wedge that comes with it.
LOGF="$HOME/bench/logs/${CNAME}.log"
mkdir -p "$HOME/bench/logs"

setsid nohup docker run --rm --name "$CNAME" \
  --memory=12g --memory-swap=12g \
  -v "$(pwd)":/aider \
  -v "$(pwd)/tmp.benchmarks/.":/benchmarks \
  -e OPENAI_API_BASE="http://${GW}:${PORT}/v1" \
  -e OPENAI_API_KEY=local-no-key-needed \
  -e AIDER_BENCHMARK_DIR=/benchmarks \
  -e AIDER_DOCKER=1 \
  -e PYTHONUNBUFFERED=1 \
  -e HEALTH_URL="http://${GW}:${PORT}/health" \
  -e RUN_NAME="$NAME" \
  -e EDIT_FMT="$FMT" \
  -e LANG_FLAG="$LANGFLAG" \
  -e NUM_TESTS="$NTESTS" \
  aider-benchmark \
  bash -c "$INNER" > "$LOGF" 2>&1 < /dev/null &

sleep 6
echo "launched: $CNAME"
echo "  model   http://${GW}:${PORT}/v1"
echo "  log     $LOGF"
echo "  follow  tail -f $LOGF"
docker ps --format "  running {{.Names}}  {{.Status}}" -f "name=$CNAME"
