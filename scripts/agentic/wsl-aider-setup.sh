#!/usr/bin/env bash
# Set up aider's OFFICIAL polyglot benchmark in WSL, in its own container.
#
# Why the official harness and not a reimplementation: the public leaderboard
# measures aider-the-tool driving a model - its prompts, its edit formats, its
# retry behaviour. A different runner is a different measurement even on
# identical tasks, and the whole reason for choosing this benchmark was that
# the numbers can be set beside other people's.
#
# Why the container: the benchmark EXECUTES code the model writes. The README
# says Docker "helps limit the damage that could be done", and that is not
# ceremony - this run will generate and execute several hundred programs from
# a 2-bit quantised model. It also carries the six language toolchains, so the
# host does not need Go, a JDK, or a C++ compiler installed.
#
# The model is NOT served from here. llama-server keeps the GPU natively on
# Windows and this reaches it over HTTP, which avoids needing CUDA inside WSL.
set -u
WORK="$HOME/bench"
cd "$WORK/aider" || { echo "aider clone missing - run the recon script first"; exit 1; }

echo "=== exercises ==="
mkdir -p tmp.benchmarks
if [ ! -d tmp.benchmarks/polyglot-benchmark ]; then
  git clone --depth 1 https://github.com/Aider-AI/polyglot-benchmark.git \
      tmp.benchmarks/polyglot-benchmark 2>&1 | tail -2
else
  echo "  already cloned"
fi
echo "  languages present:"
ls tmp.benchmarks/polyglot-benchmark/ 2>/dev/null | head -12
echo "  exercise count per language:"
for d in tmp.benchmarks/polyglot-benchmark/*/; do
  lang=$(basename "$d")
  n=$(find "$d" -maxdepth 3 -name ".meta" -type d 2>/dev/null | wc -l)
  [ "$n" = "0" ] && n=$(ls "$d/exercises/practice" 2>/dev/null | wc -l)
  printf "    %-14s %s\n" "$lang" "$n"
done
echo "  TOTAL exercises:"
find tmp.benchmarks/polyglot-benchmark -maxdepth 4 -type d -name practice -exec sh -c 'ls "$1" | wc -l' _ {} \; 2>/dev/null | paste -sd+ | bc 2>/dev/null

echo
echo "=== what the container installs ==="
grep -iE "^(FROM|RUN apt|RUN curl|ENV)" benchmark/Dockerfile 2>/dev/null | head -14

echo
echo "=== disk before build ==="
df -h / | tail -1
