#!/usr/bin/env bash
# Prove the fresh-clone Ubuntu path before trusting a machine to it.
#
# Clones this repo the way a new user would, runs the documented setup, and
# then runs the no-GPU gate. Everything is logged; nothing is interactive; the
# script never asks for a password, because a dry run that stops for a prompt
# has proved nothing about an unattended box.
#
#   bash scripts/verify/ubuntu-dryrun.sh [workdir]
#
# Exit 0 means a new user's first hour works. Any other exit names the step.
set -u

# The clone SOURCE is this checkout, found from this script's own path -- not a
# typed address. Until 2026-08-31 it defaulted to /mnt/e/AI/measured-inference,
# which is where the repo sits when Ubuntu is WSL under a Windows host. On a
# real Ubuntu box that path does not exist, so step 1 died with "CLONE FAILED"
# (exit 10) before a single thing about the box had been proved -- the one
# script whose whole job is to prove the fresh-clone path could not run on the
# platform it is named after. MI_SRC still overrides, for cloning some other
# tree deliberately.
SELF_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SRC="${MI_SRC:-$(git -C "$SELF_DIR" rev-parse --show-toplevel 2>/dev/null || (cd "$SELF_DIR/../.." && pwd))}"

WORK="${1:-$HOME/mi-dryrun}"
LOG="$WORK/dryrun.log"

rm -rf "$WORK"; mkdir -p "$WORK"
exec > >(tee -a "$LOG") 2>&1

step() { printf '\n======== %s ========\n' "$1"; }
t0=$(date +%s)

step "0. box"
. /etc/os-release 2>/dev/null; echo "distro : ${PRETTY_NAME:-unknown}"
echo "python : $(python3 -V 2>&1)"
echo "cmake  : $(cmake --version 2>/dev/null | head -1)"
echo "nvcc   : $(nvcc --version 2>/dev/null | tail -2 | head -1)"
nvidia-smi --query-gpu=name,memory.total,driver_version --format=csv,noheader 2>/dev/null \
  || echo "gpu    : no nvidia-smi"

step "1. clone, as a new user would"
git clone -q "$SRC" "$WORK/repo" || { echo "CLONE FAILED"; exit 10; }
cd "$WORK/repo" || exit 10
echo "head   : $(git rev-parse --short HEAD)"
echo "mode   : $(ls -l scripts/setup.sh | cut -c1-10) scripts/setup.sh"
[ -x scripts/setup.sh ] || { echo "FAIL: setup.sh is not executable on a fresh clone"; exit 11; }

step "2. the one command the README says needs a human"
# Never prompt. -n fails immediately without a password rather than blocking a
# background run forever, which is the whole point of this script.
NOVENV=""
if python3 -c 'import venv, ensurepip' 2>/dev/null; then
  echo "python3-venv : already present"
else
  echo "python3-venv : MISSING - this is the gap the documented apt line covers"
  if sudo -n true 2>/dev/null; then
    echo "  passwordless sudo available, installing"
    sudo -n apt-get install -y -qq python3-venv >/dev/null 2>&1 \
      && echo "  installed" || echo "  install FAILED"
  else
    echo "  no passwordless sudo. Run this yourself, then re-run:"
    echo "      sudo apt-get install -y python3-venv"
  fi
  python3 -c 'import venv, ensurepip' 2>/dev/null || NOVENV="--no-venv"
fi
[ -n "$NOVENV" ] && echo "PROCEEDING WITH $NOVENV so the CUDA build is still proved"

step "3. setup.sh --cuda   (the long one: source build)"
s0=$(date +%s)
# shellcheck disable=SC2086
./scripts/setup.sh --cuda $NOVENV
SETUP_RC=$?
echo "setup exit=$SETUP_RC after $(( $(date +%s) - s0 ))s"

step "4. what setup actually produced"
[ -f bin/llama.cpp/INSTALL.json ] && cat bin/llama.cpp/INSTALL.json || echo "no INSTALL.json"
ls -la bin/llama.cpp/ 2>/dev/null | head -12

# THE interpreter, not any interpreter. setup.sh provisions .venv and installs
# requirements into it; the system python3 has none of them. Running the gate
# with the wrong one reports a clean setup as three failures, which is exactly
# what it did on 2026-08-30 before this line existed.
PY=python3
[ -x .venv/bin/python ] && PY=./.venv/bin/python
echo "interpreter: $PY"

step "5. the resolver's own answer"
$PY scripts/lib/paths.py || echo "paths.py exit=$?"

step "6. the no-GPU gate"
$PY scripts/verify/run-all.py
GATE_RC=$?

step "7. verdict"
echo "setup   exit $SETUP_RC"
echo "gate    exit $GATE_RC"
echo "elapsed $(( $(date +%s) - t0 ))s"
echo "log     $LOG"
if [ "$SETUP_RC" -eq 0 ] && [ "$GATE_RC" -eq 0 ]; then
  echo "RESULT: a fresh clone on this box sets itself up and passes the gate."
  exit 0
fi
echo "RESULT: NOT clean. Read the step above that failed."
exit 1
