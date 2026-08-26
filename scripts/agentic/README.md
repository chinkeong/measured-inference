# Read-then-edit: aider's polyglot benchmark against a local llama-server

Every scored coding task elsewhere in this campaign is **greenfield** — "write a
program that does X", starting from an empty file. That measures fluency. It
cannot see a model that writes confident, well-formed code which changes the
wrong line, and it is not what anyone actually does with a local model: they
open code they already have and want one thing changed.

This measures the other skill.

## Why aider's benchmark and not one we wrote

A bespoke bug-injection test would have no comparability, and the first question
from any audience is "why not the standard one?". So this runs **aider's
official harness, unmodified, in aider's own container**. The public leaderboard
measures *aider-the-tool driving a model* — its prompts, its edit formats, its
retries — so a different runner is a different measurement even on identical
tasks, and the rows would stop being comparable.

**225 exercises across six languages** (C++ 26, Go 39, Java 47, JavaScript 49,
Python 34, Rust 30), each scored by running that exercise's real test suite.
No judge, no opinion: the tests pass or they do not.

## Why not SWE-bench

Two independent blockers, both worth stating rather than hiding:

1. **Context.** This page's own citation measures DeepSWE at ~1,010,000 prompt
   tokens per task against 21,700 completion. This model's native maximum is
   262,144 — **3.9x over the whole window for a single task**.
2. **Docker was absent on the Windows host.** (It exists inside WSL, which is
   how this runs at all.)

The first is the one that matters and it is arithmetic, not opinion.

## Architecture, and why it is split across two systems

    llama-server (Windows)  --GPU native, bound 0.0.0.0
              ^
              | HTTP, via the WSL default gateway
              |
    docker container (WSL Ubuntu 24.04)  --aider + six toolchains

The model keeps the GPU **natively on Windows**, so no CUDA is needed inside
WSL and every speed and VRAM figure stays comparable with everything else this
campaign measured. The benchmark runs in the container because it **executes
code the model writes** — several hundred programs from a quantised model — and
because the container carries Go, a JDK and a C++ compiler that the Windows
host does not have.

**The gateway address is discovered, never hardcoded.** WSL's address for the
Windows host changes between restarts.

## Two guards against a silent zero

Both were added on 2026-08-26 after an interrupted run left an orphaned
container working against a dead server, and both were then verified by
deliberately breaking a run.

**Pre-flight** — refuses to start unless `/health` returns 200. This fired for
real: a server still loading its model answers **HTTP 503**, and a benchmark
that starts then scores zeros on its first exercises and never says why.

**Watchdog** — polls the model every 30 s from inside the container and aborts
after two consecutive failures. Verified by killing `llama-server` mid-exercise:
it caught it in **42 seconds** and stopped the run. Without it the harness
marches through every remaining exercise collecting timeouts and produces a
tidy, complete-looking **all-zero score** — which is indistinguishable from a
real result.

That failure shape — exit 0, plausible output, nothing to catch the eye — cost
this campaign three separate defects in one week. It is worth building the
check in.

## Running it

    # once
    bash wsl-aider-recon.sh     # clone aider, report what the benchmark needs
    bash wsl-aider-setup.sh     # clone the 225 exercises, inspect the container
    cd ~/bench/aider && ./benchmark/docker_build.sh

    # each run: <name> <port> <edit-format> <languages|all> <num-tests|-1>
    bash aider-bench.sh iq4xs-whole 1283 whole all -1

Start `llama-server` on Windows with `--host 0.0.0.0` and **wait for
`{"status":"ok"}` specifically** — any-HTTP-response is not ready, as the 503
above shows.

## Measured so far

Smoke test, UD-IQ4_XS, `whole` format, reasoning off: **57.3 s per case**, so a
full 225-exercise run is about **3.6 hours** per file. On two exercises it
produced **100% well-formed edits and 0 correct** — fluent, correctly
formatted, wrong. That is the pattern worth watching at full scale, and it is
precisely what the greenfield tests cannot see. Two exercises is not a result.
