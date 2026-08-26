#!/usr/bin/env bash
# Reconnaissance only - clones aider and reports what its polyglot benchmark
# needs. Installs NOTHING except the clone, so the requirements can be read
# before anything is committed to.
set -u
WORK="$HOME/bench"
mkdir -p "$WORK"
cd "$WORK" || exit 1

echo "=== network ==="
curl -s -m 10 -o /dev/null -w "  github reachable: HTTP %{http_code}\n" https://github.com/ 2>/dev/null

if [ ! -d aider ]; then
  echo "=== cloning aider (shallow) ==="
  git clone --depth 1 https://github.com/Aider-AI/aider.git aider 2>&1 | tail -2
else
  echo "=== aider already cloned ==="
fi

cd aider 2>/dev/null || { echo "clone failed"; exit 1; }
echo
echo "=== benchmark directory ==="
ls benchmark/ 2>/dev/null | head -20
echo
echo "=== does the benchmark want Docker? ==="
grep -rilE "docker" benchmark/*.md benchmark/*.py 2>/dev/null | head -5
echo "  --- mentions in the README ---"
grep -inE "docker|container" benchmark/README.md 2>/dev/null | head -8
echo
echo "=== is there a polyglot exercise set, and how big? ==="
grep -inE "polyglot|exercism|225|exercises" benchmark/README.md 2>/dev/null | head -10
echo
echo "=== how the model endpoint is configured ==="
grep -inE "OPENAI_API_BASE|openai/|--model|api_base" benchmark/README.md 2>/dev/null | head -8
