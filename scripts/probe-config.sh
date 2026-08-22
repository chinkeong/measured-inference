#!/usr/bin/env bash
# Parameterized probe (POSIX port of scripts/reference-3090/probe-config.ps1).
#
# This is the ADAPTATION SEED for Linux/macOS campaigns, not a reference-campaign
# artifact: the reference campaign ran entirely on Windows/PowerShell, so no
# number in templates/example-report.html came from this file. Port the other
# reference scripts by following the same shape.
#
# Starts a fresh llama-server with the flags you pass, waits for health, runs one
# temp-0 probe, prints t/s (server timings preferred over wall clock), surfaces
# the server's own acceptance/offload log lines, then stops the server.
#
# Usage:   ./probe-config.sh [extra llama-server args...]
# Example: ./probe-config.sh --spec-type none
#          PROBE_MODEL=models/foo.gguf PROBE_CTX=32768 ./probe-config.sh
#
# Env overrides: PROBE_MODEL PROBE_CTX PROBE_TEXT PROBE_MMPROJ PROBE_PORT
#                LLAMA_SERVER (path to llama-server)
#
# NOTE: -ngl 99 is the default here on purpose (METHODOLOGY rule 15 — llama.cpp
# counts the output projection as layer n+1; anything less silently leaves it on
# the CPU). The PowerShell original defaults to -ngl 64 and relies on callers to
# override it; do not reintroduce that.

set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

# --- resolve the server binary: env var, repo-local build, then PATH ----------
server="${LLAMA_SERVER:-}"
if [ -z "$server" ]; then
    for cand in "$repo_root/bin/llama.cpp/llama-server" "$repo_root/bin/llama.cpp/build/bin/llama-server"; do
        [ -x "$cand" ] && { server="$cand"; break; }
    done
fi
[ -z "$server" ] && server="$(command -v llama-server || true)"
if [ -z "$server" ]; then
    echo "llama-server not found: set LLAMA_SERVER, or run scripts/setup.sh" >&2
    exit 1
fi

model="${PROBE_MODEL:?set PROBE_MODEL to the .gguf to probe}"
ctx="${PROBE_CTX:-32768}"
port="${PROBE_PORT:-1234}"
probe_text="${PROBE_TEXT:-Write a detailed 500-word technical explanation of how a marine aquarium nitrogen cycle works.}"

work="${PROBE_WORK:-$(mktemp -d)}"
log="$work/server-probe.log"

stop_server() { pkill -f "llama-server.*--port $port" 2>/dev/null || true; sleep 2; }
trap stop_server EXIT
stop_server

# --- launch ------------------------------------------------------------------
args=(-m "$model" --alias probe -c "$ctx" -ngl 99 --parallel 1
      -ctk q8_0 -ctv q8_0 --jinja --host 127.0.0.1 --port "$port")
[ -n "${PROBE_MMPROJ:-}" ] && args+=(--mmproj "$PROBE_MMPROJ")
args+=("$@")

"$server" "${args[@]}" > "$log" 2>&1 &
srv=$!

healthy=0
for _ in $(seq 1 600); do
    sleep 2
    if curl -sf "http://127.0.0.1:$port/health" | grep -q '"ok"'; then healthy=1; break; fi
    if ! kill -0 "$srv" 2>/dev/null; then
        echo "server exited early; log tail:" >&2; tail -30 "$log" >&2; exit 1
    fi
done
if [ "$healthy" -ne 1 ]; then
    echo "server never became healthy; log tail:" >&2; tail -30 "$log" >&2; exit 1
fi

# --- one temp-0 probe --------------------------------------------------------
body="$(PROBE_BODY_TEXT="$probe_text" python3 -c '
import json, os
print(json.dumps({"model": "probe", "temperature": 0, "top_k": 1,
                  "max_tokens": 700,
                  "messages": [{"role": "user", "content": os.environ["PROBE_BODY_TEXT"]}]}))')"

# python3 for the clock, not `date +%s.%N` — BSD/macOS date has no %N.
start=$(python3 -c 'import time; print(time.time())')
resp="$(curl -s -X POST "http://127.0.0.1:$port/v1/chat/completions" \
        -H 'Content-Type: application/json' -d "$body")"
end=$(python3 -c 'import time; print(time.time())')

# Prefer the server's own timings (they exclude prefill); fall back to wall clock.
RESP="$resp" START="$start" END="$end" python3 - <<'PY'
import json, os
r = json.loads(os.environ["RESP"])
wall = float(os.environ["END"]) - float(os.environ["START"])
n = r.get("usage", {}).get("completion_tokens", 0)
t = r.get("timings") or {}
srv = t.get("predicted_per_second")
line = f"PROBE: {n} tok in {wall:.1f}s wall = {n/wall if wall else 0:.1f} t/s"
if srv:
    line += f" | server predicted_per_second = {srv:.1f} t/s"
    if t.get("prompt_per_second"):
        line += f" | prefill {t['prompt_per_second']:.1f} t/s"
print(line)
PY

sleep 2
grep -Ei 'accept|eval time|draft|offload|layer' "$log" | tail -6 || true
