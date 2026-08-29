#!/usr/bin/env bash
# Launch the polyglot benchmark DETACHED and return immediately.
#
#   aider-bench-detached.sh <run-name> <port> <edit-format> <languages|all> <num-tests|-1>
#
# Environment overrides, all optional:
#   LLAMA_HOST=<addr>            where THIS shell reaches llama-server
#   LLAMA_CONTAINER_HOST=<addr>  where the CONTAINER reaches llama-server
#   AIDER_DIR=<dir>              the aider checkout (default ~/bench/aider)
#   AIDER_BENCH_SKIP_CONTAINER_CHECK=1   skip the in-container reachability probe
#
# WHY DETACHED, and this is not a preference. Two full runs died on 2026-08-26
# minutes after launch, both times taking the llama-server and the benchmark
# together, both times while the run was demonstrably healthy - the second had
# scored 489 lines of exercises before it stopped. The common factor was that
# this session HELD both processes open. So it no longer does: the model is
# started by the OS rather than by the session (Start-Process on Windows,
# `gpu_lock.serve()` or `setsid nohup` on POSIX) and the benchmark under its own
# setsid'd shell, which means nothing here has to stay alive for four hours.
#
# The watchdog inside the container matters MORE in this mode, not less. With
# nothing holding the container, a model that disappears would otherwise leave
# it collecting timeouts through every remaining exercise and reporting a tidy,
# complete-looking all-zero score. That guard was verified twice on 2026-08-26,
# once staged and once for real: when the run above was killed, the container
# was orphaned with no launcher left, and it still shut itself down in 24
# seconds.
#
# WHERE THE SERVER IS - two addresses, and collapsing them into one was a bug.
# Until 2026-08-29 this script took `ip route show default | awk '{print $3}'`
# as "the host". That is the WSL2 idiom and on WSL2 it is right: WSL2 networks
# in NAT mode, so the default route points at the vEthernet (WSL) gateway,
# which IS the Windows machine running llama-server, and that same address is
# routable from inside the container. On NATIVE Linux the identical command
# returns the LAN ROUTER, and in THIS script the mistake is quieter still: it
# detaches, returns 0, and leaves a log file that fills with timeouts.
#
# So the platform is detected rather than assumed (WSL sets WSL_DISTRO_NAME and
# puts "microsoft" in /proc/sys/kernel/osrelease), and TWO addresses are
# resolved:
#
#   HOST_ADDR       how this shell reaches the server - the pre-flight check
#   CONTAINER_ADDR  how the CONTAINER reaches it - OPENAI_API_BASE, HEALTH_URL
#
# On WSL2 they are the same string, which is why one variable was enough for as
# long as only WSL2 ran this. On native Linux the server is on this machine, so
# HOST_ADDR is 127.0.0.1 - and 127.0.0.1 inside a container is the CONTAINER.
# There the container gets `host.docker.internal`, mapped with
# `--add-host=host.docker.internal:host-gateway`, which is Docker's documented
# way to reach the host from a bridge-network container (CITED: Docker >= 20.10;
# not measured on this rig). Both addresses are printed before anything starts,
# and both are overridable.
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
AIDER_DIR="${AIDER_DIR:-$HOME/bench/aider}"

# ---- platform: WSL2 or native Linux ---------------------------------------
# WSL2 exposes both markers and either alone is enough: every WSL2 kernel
# carries "microsoft" in /proc/sys/kernel/osrelease, and the WSL init sets
# WSL_DISTRO_NAME for interactive and `wsl -e` shells alike.
PLATFORM=native
if [ -n "${WSL_DISTRO_NAME:-}" ] ||
   grep -qi microsoft /proc/sys/kernel/osrelease 2>/dev/null; then
  PLATFORM=wsl2
fi

# ---- HOST_ADDR: how THIS shell reaches llama-server ------------------------
if [ -n "${LLAMA_HOST:-}" ]; then
  HOST_ADDR="$LLAMA_HOST"
  HOST_WHY="LLAMA_HOST"
elif [ "$PLATFORM" = wsl2 ]; then
  # NAT mode: the default gateway is the Windows host, and it changes between
  # restarts, so it is discovered every run and never hardcoded.
  HOST_ADDR=$(ip route show default 2>/dev/null | awk '{print $3; exit}')
  HOST_WHY="WSL2 NAT gateway - this is the Windows host"
else
  # Native Linux: the same default route is the LAN router. The server is on
  # this machine, or LLAMA_HOST says where it is.
  HOST_ADDR=127.0.0.1
  HOST_WHY="native Linux - llama-server runs on this machine"
fi
[ -z "$HOST_ADDR" ] &&
  { echo "cannot resolve the llama-server address; set LLAMA_HOST=<addr>"; exit 1; }

# ---- CONTAINER_ADDR: how the CONTAINER reaches llama-server ---------------
ADDHOST=""
if [ -n "${LLAMA_CONTAINER_HOST:-}" ]; then
  CONTAINER_ADDR="$LLAMA_CONTAINER_HOST"
  CONT_WHY="LLAMA_CONTAINER_HOST"
elif [ "$PLATFORM" = wsl2 ]; then
  CONTAINER_ADDR="$HOST_ADDR"
  CONT_WHY="the WSL gateway is routable from the container too"
elif [ "$HOST_ADDR" = "127.0.0.1" ] || [ "$HOST_ADDR" = "localhost" ] ||
     [ "$HOST_ADDR" = "::1" ]; then
  CONTAINER_ADDR="host.docker.internal"
  ADDHOST="--add-host=host.docker.internal:host-gateway"
  CONT_WHY="loopback in a container is the container; --add-host maps the host"
else
  CONTAINER_ADDR="$HOST_ADDR"
  CONT_WHY="not a loopback - the container uses the same address"
fi

HEALTH_CONT="http://${CONTAINER_ADDR}:${PORT}/health"
HEALTH_HOST="http://${HOST_ADDR}:${PORT}/health"

echo "platform   $PLATFORM"
echo "host       http://${HOST_ADDR}:${PORT}   ($HOST_WHY)"
echo "container  http://${CONTAINER_ADDR}:${PORT}   ($CONT_WHY)"

cd "$AIDER_DIR" 2>/dev/null ||
  { echo "no aider checkout at $AIDER_DIR (set AIDER_DIR)"; exit 1; }

# Pre-flight: refuse to start against a server that is not READY. Anything
# other than 200 counts - a server still loading a model answers HTTP 503, and
# a benchmark that starts then scores zeros on its first exercises and never
# says why. This fired for real on 2026-08-26.
code=$(curl -s -m 8 -o /dev/null -w '%{http_code}' "$HEALTH_HOST")
if [ "$code" != "200" ]; then
  echo "ABORT: llama-server not ready at ${HEALTH_HOST} (HTTP ${code})"
  echo "  server somewhere else?   LLAMA_HOST=<addr> $0 $*"
  echo "  WSL2, mirrored mode?     the default route is the LAN router there,"
  echo "                           not Windows - set LLAMA_HOST explicitly"
  exit 1
fi

# A host-side 200 does NOT prove the CONTAINER can reach the model, and that
# gap is the exact shape of the gateway bug above: the launcher checks one
# address while the benchmark uses another. Detached, nobody is watching, so
# probe the real URL from inside the real image before returning a launch this
# shell will not see fail - one container start, about a second.
if [ "${AIDER_BENCH_SKIP_CONTAINER_CHECK:-0}" != "1" ]; then
  # $ADDHOST is deliberately unquoted: empty must expand to no argument at all.
  cc=$(docker run --rm $ADDHOST aider-benchmark \
       bash -c "curl -s -m 8 -o /dev/null -w '%{http_code}' '$HEALTH_CONT'" \
       2>/dev/null)
  if [ -z "$cc" ]; then
    # curl always prints three digits when it runs at all, so an empty answer
    # means the container never started - a missing image, not a network.
    echo "ABORT: the container did not run. Is the aider-benchmark image built?"
    echo "  docker images aider-benchmark"
    exit 1
  fi
  if [ "$cc" != "200" ]; then
    echo "ABORT: the CONTAINER cannot reach ${HEALTH_CONT} (HTTP ${cc})"
    echo "  the host can reach it, so this is container networking, not a dead"
    echo "  server. Set LLAMA_CONTAINER_HOST=<addr the container can see>, or"
    echo "  AIDER_BENCH_SKIP_CONTAINER_CHECK=1 to run anyway."
    exit 1
  fi
fi

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
  --memory=12g --memory-swap=12g $ADDHOST \
  -v "$(pwd)":/aider \
  -v "$(pwd)/tmp.benchmarks/.":/benchmarks \
  -e OPENAI_API_BASE="http://${CONTAINER_ADDR}:${PORT}/v1" \
  -e OPENAI_API_KEY=local-no-key-needed \
  -e AIDER_BENCHMARK_DIR=/benchmarks \
  -e AIDER_DOCKER=1 \
  -e PYTHONUNBUFFERED=1 \
  -e HEALTH_URL="$HEALTH_CONT" \
  -e RUN_NAME="$NAME" \
  -e EDIT_FMT="$FMT" \
  -e LANG_FLAG="$LANGFLAG" \
  -e NUM_TESTS="$NTESTS" \
  aider-benchmark \
  bash -c "$INNER" > "$LOGF" 2>&1 < /dev/null &

sleep 6
echo "launched: $CNAME"
echo "  model   http://${CONTAINER_ADDR}:${PORT}/v1   (as the container sees it)"
echo "  log     $LOGF"
echo "  follow  tail -f $LOGF"
docker ps --format "  running {{.Names}}  {{.Status}}" -f "name=$CNAME"
