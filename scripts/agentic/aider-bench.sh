#!/usr/bin/env bash
# Run aider's OFFICIAL polyglot benchmark against llama-server, inside aider's
# own container.
#
#   aider-bench.sh <run-name> <port> <edit-format> <languages|all> <num-tests|-1>
#
# Environment overrides, all optional:
#   LLAMA_HOST=<addr>            where THIS shell reaches llama-server
#   LLAMA_CONTAINER_HOST=<addr>  where the CONTAINER reaches llama-server
#   AIDER_DIR=<dir>              the aider checkout (default ~/bench/aider)
#   AIDER_BENCH_SKIP_CONTAINER_CHECK=1   skip the in-container reachability probe
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
# WHERE THE SERVER IS - two addresses, and collapsing them into one was a bug.
# Until 2026-08-29 this script took `ip route show default | awk '{print $3}'`
# as "the host". That is the WSL2 idiom and on WSL2 it is right: WSL2 networks
# in NAT mode, so the default route points at the vEthernet (WSL) gateway,
# which IS the Windows machine running llama-server, and that same address is
# routable from inside the container. On NATIVE Linux the identical command
# returns the LAN ROUTER. Nothing fails at launch - the benchmark starts, talks
# to a router, and the mistake surfaces hours later as Stage-6 zeros.
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
if [ -z "$HOST_ADDR" ]; then
  echo "cannot resolve the llama-server address; set LLAMA_HOST=<addr>"
  exit 1
fi

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

BASE="http://${CONTAINER_ADDR}:${PORT}/v1"
HEALTH_CONT="http://${CONTAINER_ADDR}:${PORT}/health"
HEALTH_HOST="http://${HOST_ADDR}:${PORT}/health"

echo "platform   $PLATFORM"
echo "host       http://${HOST_ADDR}:${PORT}   ($HOST_WHY)"
echo "container  http://${CONTAINER_ADDR}:${PORT}   ($CONT_WHY)"

cd "$AIDER_DIR" 2>/dev/null ||
  { echo "no aider checkout at $AIDER_DIR (set AIDER_DIR)"; exit 1; }

code=$(curl -s -m 8 -o /dev/null -w '%{http_code}' "$HEALTH_HOST")
if [ "$code" != "200" ]; then
  echo "ABORT: llama-server not reachable at ${HEALTH_HOST} (HTTP ${code})"
  echo "  server somewhere else?   LLAMA_HOST=<addr> $0 $*"
  echo "  WSL2, mirrored mode?     the default route is the LAN router there,"
  echo "                           not Windows - set LLAMA_HOST explicitly"
  exit 1
fi

# A host-side 200 does NOT prove the CONTAINER can reach the model, and that
# gap is the exact shape of the gateway bug above: the launcher checks one
# address while the benchmark uses another. So probe the real URL from inside
# the real image before committing to the run - one container start, about a
# second, against four hours of zeros.
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
  echo "container reached the model; container name ${CNAME}"
else
  echo "container check SKIPPED; container name ${CNAME}"
fi

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
  --memory=12g --memory-swap=12g $ADDHOST \
  -v "$(pwd)":/aider \
  -v "$(pwd)/tmp.benchmarks/.":/benchmarks \
  -e OPENAI_API_BASE="$BASE" \
  -e OPENAI_API_KEY=local-no-key-needed \
  -e AIDER_BENCHMARK_DIR=/benchmarks \
  -e AIDER_DOCKER=1 \
  -e HEALTH_URL="$HEALTH_CONT" \
  -e RUN_NAME="$NAME" \
  -e EDIT_FMT="$FMT" \
  -e LANG_FLAG="$LANGFLAG" \
  -e NUM_TESTS="$NTESTS" \
  aider-benchmark \
  bash -c "$INNER"
