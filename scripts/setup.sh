#!/usr/bin/env bash
# Bootstrap a self-contained llama.cpp into <repo>/bin/llama.cpp/ -- no root,
# nothing outside the repo tree -- plus the Python venv the harness runs in.
#
#   ./scripts/setup.sh --cuda     # NVIDIA: build CUDA from source (the measuring path)
#   ./scripts/setup.sh            # Intel / AMD / Apple / CPU: official binary release
#   ./scripts/setup.sh --help
#
# WHY --cuda EXISTS, AND WHY NVIDIA WITHOUT IT IS NOW A HARD ERROR
# There are no official Linux CUDA binaries (checked b10582, any arch). This
# script used to answer that by installing the Vulkan build on an NVIDIA box "as
# a usable fallback" and carrying on with exit 0. But the backend is a condition
# of every number: swap CUDA for Vulkan and prefill, decode, acceptance and the
# VRAM ceiling all move for a reason that has nothing to do with the model, so a
# rerun silently stops being comparable to the campaign it is rerunning
# (METHODOLOGY rule 3 -- a number without its conditions is unfalsifiable;
# rule 30 -- compare arms inside one sweep, never across). A different backend is
# not a fallback, it is a different experiment.
#
# So: NVIDIA + non-CUDA exits non-zero unless MEASURED_INFERENCE_ALLOW_VULKAN=1,
# and whatever is installed is recorded in bin/llama.cpp/INSTALL.json so every
# report can state which backend produced its numbers.
#
# Exit codes: 2 usage . 3 backend/toolchain refusal . 4 install or verify failed
#             5 frozen inputs mangled (CRLF) . 6 Python/venv unusable
set -euo pipefail

# ---- Asset name patterns (grep -E, matched against browser_download_url basenames) -------------
# Verified against release b10582 (2026-08-22). Names drift between releases; fix here if selection fails.
PAT_VULKAN_X64='llama-b[0-9]+-bin-ubuntu-vulkan-x64\.tar\.gz$'
PAT_CPU_X64='llama-b[0-9]+-bin-ubuntu-x64\.tar\.gz$'
PAT_CPU_ARM64='llama-b[0-9]+-bin-ubuntu-arm64\.tar\.gz$'        # official Linux ARM64 CPU build exists
PAT_VULKAN_ARM64='llama-b[0-9]+-bin-ubuntu-vulkan-arm64\.tar\.gz$'
PAT_MACOS_ARM64='llama-b[0-9]+-bin-macos-arm64\.tar\.gz$'       # Apple Silicon: Metal built in
PAT_MACOS_X64='llama-b[0-9]+-bin-macos-x64\.tar\.gz$'           # Intel Mac: CPU-only
TAG_RE='^b[0-9]+$'  # binary releases are tagged bNNNNN; /releases/latest points elsewhere (v0.2.0 nightly tracker)
UPSTREAM='https://github.com/ggml-org/llama.cpp'
# Every llama.cpp tool this repo shells out to. llama-server is fatal if it fails
# to build; the rest are reported and skipped.
TOOLS_REQUIRED='llama-server'
TOOLS_OPTIONAL='llama-perplexity llama-cli llama-bench llama-tokenize llama-mtmd-cli'
# ------------------------------------------------------------------------------------------------

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
DEST="$ROOT/bin/llama.cpp"; DL="$DEST/.downloads"; VFILE="$DEST/VERSION.txt"
EXE="$DEST/llama-server"; SRC="$DEST/.src/llama.cpp"; INSTALL_JSON="$DEST/INSTALL.json"

info() { printf '[setup] %s\n' "$*"; }
warn() { printf '[setup] WARNING: %s\n' "$*" >&2; }
die()  { printf '[setup] ERROR: %s\n' "$1" >&2; exit "${2:-1}"; }
have() { command -v "$1" >/dev/null 2>&1; }
cpu_count() { if have nproc; then nproc; else sysctl -n hw.ncpu 2>/dev/null || echo 4; fi; }

json_str() {
  local s
  s="$(printf '%s' "${1-}" | tr -d '\r\n\t')"
  s="${s//\\/\\\\}"
  s="${s//\"/\\\"}"
  printf '"%s"' "$s"
}
# "" would read as "asked and got nothing"; null is "not applicable here"
json_or_null() { if [ -z "${1-}" ]; then printf 'null'; else json_str "$1"; fi; }

usage() {
  cat <<'USAGE'
Usage: scripts/setup.sh [options]

  -f, --force        reinstall even if this release+flavor is already present
      --cuda         build llama.cpp from source with CUDA (NVIDIA; needs nvcc,
                     cmake, git, a C++ toolchain). = MEASURED_INFERENCE_BUILD_CUDA=1
      --cuda-arch A  value for -DCMAKE_CUDA_ARCHITECTURES (default: native;
                     DGX Spark GB10 wants 121 when native fails)
      --tag bNNNNN   pin a llama.cpp release instead of taking the newest one.
                     Pin it when a rerun must match an earlier campaign's build
      --publish      install requirements.txt (plots/stats) instead of requirements-min.txt
      --no-venv      skip the .venv step entirely (you manage Python yourself)
      --allow-vulkan accept a non-CUDA backend on an NVIDIA GPU (see below)
      --dry-run      detect, decide and print the plan; touch nothing, download nothing
  -h, --help         this text

Environment:
  MEASURED_INFERENCE_BUILD_CUDA=1    same as --cuda
  MEASURED_INFERENCE_ALLOW_VULKAN=1  same as --allow-vulkan
  MEASURED_INFERENCE_CUDA_ARCH=...   same as --cuda-arch
  MEASURED_INFERENCE_ALLOW_CRLF=1    proceed even if a frozen input no longer matches its
                                     committed bytes (usually CRLF rewriting)
  MEASURED_INFERENCE_DRY_RUN=1       same as --dry-run (the gpu_lock convention)
  CUDA_HOME / CUDA_PATH              searched for bin/nvcc when nvcc is not on PATH

On an NVIDIA GPU, any backend other than CUDA changes every throughput number for
a reason unrelated to the model, so setup EXITS NON-ZERO rather than installing
one quietly. Either build CUDA (--cuda) or say --allow-vulkan and accept that
those numbers are not comparable to a CUDA campaign.
USAGE
}

# ---------------------------------------------------------------- 0. arguments
FORCE=0; WANT_CUDA="${MEASURED_INFERENCE_BUILD_CUDA:-0}"; PUBLISH=0; DO_VENV=1
DRY="${MEASURED_INFERENCE_DRY_RUN:-0}"
ALLOW_VULKAN="${MEASURED_INFERENCE_ALLOW_VULKAN:-0}"
ALLOW_CRLF="${MEASURED_INFERENCE_ALLOW_CRLF:-0}"
CUDA_ARCH="${MEASURED_INFERENCE_CUDA_ARCH:-native}"
TAG=""; TAG_PINNED=0
while [ $# -gt 0 ]; do
  case "$1" in
    -f|--force)      FORCE=1 ;;
    --cuda)          WANT_CUDA=1 ;;
    --cuda-arch)     CUDA_ARCH="${2:?--cuda-arch needs a value}"; shift ;;
    --tag)           TAG="${2:?--tag needs a value}"; TAG_PINNED=1; shift ;;
    --publish)       PUBLISH=1 ;;
    --no-venv)       DO_VENV=0 ;;
    --allow-vulkan)  ALLOW_VULKAN=1 ;;
    --dry-run)       DRY=1 ;;
    -h|--help)       usage; exit 0 ;;
    *) usage >&2; die "unknown option '$1'" 2 ;;
  esac
  shift
done
if [ "$TAG_PINNED" -eq 1 ] && ! printf '%s' "$TAG" | grep -qE "$TAG_RE"; then
  die "--tag '$TAG' does not look like a llama.cpp binary release (bNNNNN)." 2
fi
[ "$DRY" = 1 ] && info "DRY RUN: nothing is downloaded, built, written or installed."

# ------------------------------------------------- 1. frozen inputs, byte-exact
# Cheap, and it runs before anything expensive. Git-for-Windows defaults to
# core.autocrlf=true, and a clone made before .gitattributes existed has every
# LF in corpora/wikitext-2-raw-test.raw rewritten to CRLF: 1,290,590 bytes
# become 1,294,948, and the quant ranking (rule 6, perplexity over 294,912 token
# positions) is then computed over a different file than the published one. Same
# hazard for the frozen datasets and rule 23's suite hashes.
#
# The test is byte size against the COMMITTED blob, not "does it contain CR".
# One frozen input, meetingbank_test.jsonl, is legitimately CRLF in git; a
# CR-hunting heuristic condemns it on every platform. What matters is only
# whether the checkout still matches what was committed.
FROZEN_STATE=unverified   # unverified | match | rewritten
check_frozen_inputs() {
  local rel want got bad=0 checked=0
  [ -f "$ROOT/.gitattributes" ] || warn "no .gitattributes at the repo root -- '* -text' is what stops a Windows clone rewriting the frozen inputs."
  if ! have git || ! git -C "$ROOT" rev-parse --git-dir >/dev/null 2>&1; then
    info "Frozen inputs: NOT VERIFIED -- no git metadata here to compare the bytes against."
    return 0
  fi
  while IFS= read -r rel; do
    [ -n "$rel" ] && [ -f "$ROOT/$rel" ] || continue
    want="$(git -C "$ROOT" cat-file -s "HEAD:$rel" 2>/dev/null || true)"
    [ -n "$want" ] || continue
    got="$(wc -c < "$ROOT/$rel" | tr -d ' ')"
    checked=$((checked + 1))
    if [ "$want" != "$got" ]; then
      bad=1
      warn "frozen input does not match its commit: $rel (committed $want bytes, on disk $got)"
    fi
  done <<FROZEN_LIST
$(git -C "$ROOT" ls-files -- corpora scripts/bench/datasets-frozen 2>/dev/null || true)
FROZEN_LIST
  if [ "$bad" -eq 0 ]; then
    FROZEN_STATE=match
    info "Frozen inputs: $checked files byte-identical to their commit."
    return 0
  fi
  FROZEN_STATE=rewritten
  if [ "$ALLOW_CRLF" = 1 ]; then
    warn "MEASURED_INFERENCE_ALLOW_CRLF=1 -- continuing with rewritten inputs. No perplexity or suite hash from this clone is comparable to a published one."
    return 0
  fi
  cat >&2 <<CRLF_HELP
[setup] These bytes are data, not formatting, and this checkout no longer matches
[setup] what was committed -- the usual cause is git core.autocrlf rewriting LF to
[setup] CRLF on a Windows clone. Perplexity here would be computed over a different
[setup] file than the published ranking was (rule 6), and suite hashes will not
[setup] match (rule 23).
[setup] Fix, from $ROOT:
[setup]     git config core.autocrlf false
[setup]     git rm --cached -r . >/dev/null && git reset --hard
[setup] Then re-run this script. Override with MEASURED_INFERENCE_ALLOW_CRLF=1 only
[setup] if no perplexity or dataset number from this clone will ever be published.
CRLF_HELP
  exit 5
}
check_frozen_inputs

# --------------------------------------------------- 2. detect OS + arch + GPU
OS="$(uname -s)"; ARCH="$(uname -m)"; GPU="none"; GPU_NAME=""; DRIVER=""
OS_DESC="$(uname -sr 2>/dev/null || uname -s)"
# "os" is a TOKEN, matching what scripts/detect-machine.py compares against
# ({'win32':'windows','darwin':'macos'}.get(sys.platform,'linux')); the
# readable string goes in "os_version".
case "$OS" in
  Linux)                    OS_TOKEN=linux ;;
  Darwin)                   OS_TOKEN=macos ;;
  MINGW*|MSYS*|CYGWIN*|Windows_NT) OS_TOKEN=windows ;;
  *)                        OS_TOKEN="$(printf %s "$OS" | tr '[:upper:]' '[:lower:]')" ;;
esac
if [ -r /etc/os-release ]; then
  PRETTY="$(grep -E '^PRETTY_NAME=' /etc/os-release | head -1 | cut -d= -f2- | tr -d '"' || true)"
  [ -n "${PRETTY:-}" ] && OS_DESC="$PRETTY ($OS_DESC)"
fi
if [ "$OS" = "Darwin" ]; then
  case "$ARCH" in
    arm64)  PAT_LIST="metal:$PAT_MACOS_ARM64"; GPU="apple" ;;  # Metal is built into the official arm64 binary
    x86_64) PAT_LIST="cpu:$PAT_MACOS_X64" ;;                   # Intel Mac: CPU-only official build
    *) die "Unsupported macOS arch '$ARCH' -- build from source (cmake -B build && cmake --build build --target llama-server)." 3 ;;
  esac
else
  if have nvidia-smi && nvidia-smi -L >/dev/null 2>&1; then
    GPU="nvidia"
    GPU_NAME="$(nvidia-smi --query-gpu=name --format=csv,noheader 2>/dev/null | head -1 || true)"
    DRIVER="$(nvidia-smi --query-gpu=driver_version --format=csv,noheader 2>/dev/null | head -1 || true)"
  elif have lspci; then
    VGA="$(lspci 2>/dev/null | grep -iE 'vga|3d controller' || true)"
    case "$VGA" in *[Ii]ntel*|*AMD*|*ATI*) GPU="vulkan-capable";; esac
  fi
  # Both arches take the SAME branch on purpose. aarch64 used to read
  # `if [ "$GPU" = "vulkan-capable" ]`, and nvidia-smi sets GPU to "nvidia" --
  # so PAT_VULKAN_ARM64 was unreachable and a DGX Spark GB10 (aarch64 + NVIDIA,
  # see reference/platform-notes.md) silently got a CPU-only build: a GPU field
  # guide measured on the CPU.
  case "$ARCH" in
    x86_64|amd64)
      if [ "$GPU" = "none" ]; then PAT_LIST="cpu:$PAT_CPU_X64"
      else PAT_LIST="vulkan:$PAT_VULKAN_X64 cpu:$PAT_CPU_X64"; fi ;;
    aarch64|arm64)
      if [ "$GPU" = "none" ]; then PAT_LIST="cpu:$PAT_CPU_ARM64"
      else PAT_LIST="vulkan:$PAT_VULKAN_ARM64 cpu:$PAT_CPU_ARM64"; fi ;;
    *) die "Unsupported arch '$ARCH' -- no official binaries; build from source." 3 ;;
  esac
fi
FLAVOR="${PAT_LIST%%:*}"   # intended flavor; the asset that actually matches decides
info "os=$OS arch=$ARCH gpu=$GPU${GPU_NAME:+ ($GPU_NAME, driver $DRIVER)}"

# ------------------------------------------------ 3. CUDA: opt-in source build
find_nvcc() {
  local c
  if have nvcc; then command -v nvcc; return 0; fi
  for c in "${CUDA_HOME:-}" "${CUDA_PATH:-}" /usr/local/cuda /opt/cuda /usr/lib/nvidia-cuda-toolkit; do
    if [ -n "$c" ] && [ -x "$c/bin/nvcc" ]; then printf '%s\n' "$c/bin/nvcc"; return 0; fi
  done
  return 1
}
NVCC=""; BUILT=false; SOURCE_COMMIT=""; BUILD_SECONDS=""
TOOLS_BUILT=""; TOOLS_MISSING=""
if [ "$WANT_CUDA" = 1 ]; then
  [ "$GPU" = "nvidia" ] || die "--cuda but no NVIDIA GPU here (nvidia-smi -L found nothing). Drop --cuda for the $FLAVOR build." 3
  NVCC="$(find_nvcc || true)"
  if [ -z "$NVCC" ]; then
    cat >&2 <<'NVCC_HELP'
[setup] ERROR: --cuda needs the CUDA toolkit, and nvcc is not on PATH (nor under
[setup]        CUDA_HOME / CUDA_PATH / /usr/local/cuda / /opt/cuda). On Ubuntu:
[setup]            sudo apt-get install -y nvidia-cuda-toolkit cmake build-essential git
[setup]        or install NVIDIA's own toolkit and re-run with:
[setup]            CUDA_HOME=/usr/local/cuda ./scripts/setup.sh --cuda
NVCC_HELP
    exit 3
  fi
  have cmake || die "--cuda needs cmake: sudo apt-get install -y cmake build-essential git" 3
  have git   || die "--cuda needs git: sudo apt-get install -y git" 3
  FLAVOR="cuda"
  info "CUDA source build requested: nvcc=$NVCC arch=$CUDA_ARCH"
fi
info "backend flavor: $FLAVOR"

# ---------------------------- 4. THE GATE: no silent backend substitution
if [ "$GPU" = "nvidia" ] && [ "$FLAVOR" != "cuda" ]; then
  if [ "$ALLOW_VULKAN" = 1 ]; then
    warn "NVIDIA GPU with a '$FLAVOR' build (--allow-vulkan / MEASURED_INFERENCE_ALLOW_VULKAN=1)."
    warn "Every number this produces is a '$FLAVOR' number. Say so in campaign.md and in the report; it is NOT comparable to a CUDA campaign."
  else
    cat >&2 <<GATE
[setup] ERROR: NVIDIA GPU detected, but the backend on offer is '$FLAVOR', not CUDA.
[setup]
[setup] There are no official Linux CUDA binaries. Installing the $FLAVOR build here
[setup] would hand you a working server whose every throughput, acceptance and VRAM
[setup] number differs from a CUDA campaign's for a reason that has nothing to do
[setup] with the model -- and nothing in the run would tell you (rule 3).
[setup]
[setup] Build CUDA instead (typically 10-25 min on a modern desktop):
[setup]     sudo apt-get install -y nvidia-cuda-toolkit cmake build-essential git
[setup]     ./scripts/setup.sh --cuda
[setup]
[setup] Or take a non-comparable backend, deliberately and on the record:
[setup]     MEASURED_INFERENCE_ALLOW_VULKAN=1 ./scripts/setup.sh
GATE
    exit 3
  fi
fi

# ------------------------------------------------------ 5. resolve the release
RELEASES_JSON=""
if [ "$TAG_PINNED" -eq 1 ]; then
  info "Release pinned by --tag: $TAG"
elif [ "$DRY" = 1 ]; then
  TAG="<newest-bNNNNN>"; info "Would query the GitHub API for the newest bNNNNN release."
else
  RELEASES_JSON="$(curl -fsSL -H 'User-Agent: measured-inference-setup' -H 'Accept: application/vnd.github+json' \
    'https://api.github.com/repos/ggml-org/llama.cpp/releases?per_page=10')" \
    || die "GitHub releases API unreachable. Offline? Pin a known release with --tag bNNNNN." 4
  TAG="$(printf '%s' "$RELEASES_JSON" | grep -oE '"tag_name": *"[^"]+"' | cut -d'"' -f4 | grep -E "$TAG_RE" | head -1 || true)"
  [ -n "$TAG" ] || die "No bNNNNN release in the 10 most recent -- check TAG_RE." 4
  info "Latest binary release: $TAG"
fi

# -------------------------------------------------------------- 6. idempotency
# INSTALL.json is part of the install, not a note about it: an install that
# cannot say which backend it is has to be redone (rule 3).
INSTALLED_FLAVOR=""
if [ -f "$INSTALL_JSON" ]; then
  INSTALLED_FLAVOR="$(grep -oE '"flavor"[[:space:]]*:[[:space:]]*"[^"]*"' "$INSTALL_JSON" | cut -d'"' -f4 | head -1 || true)"
fi
SKIP_INSTALL=0
if [ "$FORCE" -eq 0 ] && [ -f "$VFILE" ] && [ -x "$EXE" ] \
   && [ "$(head -n1 "$VFILE" 2>/dev/null | tr -d '[:space:]')" = "$TAG" ]; then
  if [ "$INSTALLED_FLAVOR" = "$FLAVOR" ]; then
    SKIP_INSTALL=1
    info "$TAG ($FLAVOR) already installed at $DEST -- skipping the install (use -f to redo it)."
  elif [ -z "$INSTALLED_FLAVOR" ]; then
    info "$TAG is installed but INSTALL.json records no flavor -- reinstalling so the backend goes on the record."
  else
    info "$TAG is installed as '$INSTALLED_FLAVOR', you asked for '$FLAVOR' -- reinstalling."
  fi
fi

# -------------------------------------------------- 7a. install: source build
ASSETS_JSON=""; URLS_JSON=""
build_from_source() {
  local t0 t1 built="" missing="" t
  t0="$(date +%s)"
  mkdir -p "$DEST/.src"
  if [ -d "$SRC/.git" ]; then
    info "Reusing the clone at $SRC (fetching $TAG)..."
    git -C "$SRC" fetch --depth 1 origin "refs/tags/$TAG:refs/tags/$TAG" >/dev/null 2>&1 \
      || git -C "$SRC" fetch --depth 1 origin "$TAG" >/dev/null 2>&1 \
      || die "git fetch of $TAG failed in $SRC (delete that directory and re-run to reclone)." 4
    git -C "$SRC" checkout -q --detach "$TAG" || die "git checkout $TAG failed in $SRC." 4
  else
    rm -rf "$SRC"
    info "Cloning $UPSTREAM @ $TAG (shallow)..."
    git clone --depth 1 --branch "$TAG" "$UPSTREAM" "$SRC" \
      || die "shallow clone of $TAG failed -- check the tag and the network." 4
  fi
  SOURCE_COMMIT="$(git -C "$SRC" rev-parse --short=12 HEAD 2>/dev/null || true)"

  info "Configuring: GGML_CUDA=ON CMAKE_CUDA_ARCHITECTURES=$CUDA_ARCH CMAKE_BUILD_TYPE=Release"
  # RPATH $ORIGIN so the binaries still find libggml*.so after being copied out
  # of build/bin into bin/llama.cpp/ -- callers Popen them directly, with no
  # LD_LIBRARY_PATH (scripts/bench/bench.py, scripts/lib/paths.py).
  cmake -S "$SRC" -B "$SRC/build" \
        -DGGML_CUDA=ON \
        -DCMAKE_CUDA_ARCHITECTURES="$CUDA_ARCH" \
        -DCMAKE_CUDA_COMPILER="$NVCC" \
        -DCMAKE_BUILD_TYPE=Release \
        -DLLAMA_BUILD_TESTS=OFF \
        -DCMAKE_BUILD_WITH_INSTALL_RPATH=ON \
        -DCMAKE_INSTALL_RPATH='$ORIGIN' \
    || die "cmake configure failed. If CMAKE_CUDA_ARCHITECTURES=native is unsupported by this nvcc (DGX Spark GB10 is the known case), retry with: ./scripts/setup.sh --cuda --cuda-arch 121" 4

  for t in $TOOLS_REQUIRED $TOOLS_OPTIONAL; do
    info "Building $t..."
    if cmake --build "$SRC/build" --config Release -j "$(cpu_count)" --target "$t"; then
      built="$built $t"
    else
      case " $TOOLS_REQUIRED " in
        *" $t "*) die "target $t failed to build -- the campaign cannot run without it." 4 ;;
        *) warn "target $t failed to build (or is absent from $TAG) -- continuing without it."; missing="$missing $t" ;;
      esac
    fi
  done

  mkdir -p "$DEST"
  for t in $built; do
    cp -f "$SRC/build/bin/$t" "$DEST/" || die "built $t but could not copy it into $DEST." 4
  done
  # the shared libs those tools link against (libggml*, libllama, libmtmd)
  find "$SRC/build/bin" -maxdepth 1 -name 'lib*.so*' -exec cp -f {} "$DEST/" \; 2>/dev/null || true
  t1="$(date +%s)"; BUILD_SECONDS="$((t1 - t0))"
  BUILT=true
  TOOLS_BUILT="${built# }"
  TOOLS_MISSING="${missing# }"
  URLS_JSON="$(json_str "$UPSTREAM")"
  info "CUDA build finished in $((BUILD_SECONDS / 60))m $((BUILD_SECONDS % 60))s (commit ${SOURCE_COMMIT:-unknown})."
  [ -n "$TOOLS_MISSING" ] && warn "not built: $TOOLS_MISSING"
  return 0
}

# ----------------------------------------------- 7b. install: binary release
download_release() {
  local entry fl pat u file
  if [ -z "$RELEASES_JSON" ]; then
    RELEASES_JSON="$(curl -fsSL -H 'User-Agent: measured-inference-setup' -H 'Accept: application/vnd.github+json' \
      "https://api.github.com/repos/ggml-org/llama.cpp/releases/tags/$TAG")" \
      || die "could not read release $TAG from the GitHub API." 4
  fi
  u=""
  # shellcheck disable=SC2086
  for entry in $PAT_LIST; do
    fl="${entry%%:*}"; pat="${entry#*:}"
    u="$(printf '%s' "$RELEASES_JSON" | grep -oE '"browser_download_url": *"[^"]+"' | cut -d'"' -f4 \
         | grep "/download/$TAG/" | grep -E "$pat" | head -1 || true)"
    if [ -n "$u" ]; then
      [ "$fl" = "$FLAVOR" ] || warn "no '$FLAVOR' asset in $TAG -- falling back to '$fl'."
      FLAVOR="$fl"; break
    fi
  done
  [ -n "$u" ] || die "no asset in $TAG matches any of: $PAT_LIST -- release naming drifted; update the patterns at the top of this script." 4
  # the gate ran on the INTENDED flavor; re-assert it on what actually landed
  if [ "$GPU" = "nvidia" ] && [ "$FLAVOR" != "cuda" ] && [ "$ALLOW_VULKAN" != 1 ]; then
    die "asset fallback landed on '$FLAVOR' for an NVIDIA GPU -- see --help." 3
  fi

  mkdir -p "$DEST" "$DL"
  file="$DL/$(basename "$u")"
  info "Downloading $(basename "$u")..."
  curl -fL -C - --retry 3 --retry-delay 2 -o "$file" "$u" || curl -fL --retry 3 -o "$file" "$u" \
    || die "download failed: $u" 4
  info "Extracting into $DEST..."
  tar -xzf "$file" --strip-components=1 -C "$DEST" || die "extract failed: $file" 4
  rm -f "$file"
  ASSETS_JSON="$(json_str "$(basename "$u")")"
  URLS_JSON="$(json_str "$u")"
}

# ------------------------------------------------------------- 8. the dry run
if [ "$DRY" = 1 ]; then
  echo ""
  info "--- plan ---"
  if [ "$SKIP_INSTALL" -eq 1 ]; then
    info "install : skip ($TAG / $FLAVOR already present)"
  elif [ "$WANT_CUDA" = 1 ]; then
    info "install : source build -> $DEST"
    info "          git clone --depth 1 --branch $TAG $UPSTREAM $SRC"
    info "          cmake -S $SRC -B $SRC/build -DGGML_CUDA=ON -DCMAKE_CUDA_ARCHITECTURES=$CUDA_ARCH -DCMAKE_BUILD_TYPE=Release"
    info "          targets: $TOOLS_REQUIRED $TOOLS_OPTIONAL"
  else
    info "install : binary release -> $DEST"
    info "          candidate assets, in order: $PAT_LIST"
  fi
  info "record  : $INSTALL_JSON  (tag, flavor=$FLAVOR, arch=$ARCH, os, assets, urls, installed_utc, built_from_source, cuda_arch)"
  if [ "$DO_VENV" = 1 ]; then
    info "python  : $ROOT/.venv + $([ "$PUBLISH" = 1 ] && echo requirements.txt || echo requirements-min.txt)"
  else
    info "python  : skipped (--no-venv)"
  fi
  info "--- end of plan; nothing was changed ---"
  exit 0
fi

if [ "$SKIP_INSTALL" -eq 0 ]; then
  if [ "$WANT_CUDA" = 1 ]; then build_from_source; else download_release; fi
fi

# ----------------------------------------------------------- 9. verify it runs
[ -x "$EXE" ] || die "llama-server not found at $EXE after the install." 4
NEEDS_LD_PATH=false
if VER_OUT="$("$EXE" --version 2>&1)"; then
  :
elif VER_OUT="$(LD_LIBRARY_PATH="$DEST" DYLD_LIBRARY_PATH="$DEST" "$EXE" --version 2>&1)"; then
  NEEDS_LD_PATH=true
  warn "llama-server only runs with LD_LIBRARY_PATH=$DEST -- its RPATH does not cover its own directory."
  warn "Export that before running any harness script, or the campaign dies at its first server launch."
else
  die "llama-server --version failed: $VER_OUT" 4
fi
VER_OUT="$(printf '%s\n' "$VER_OUT" | head -n2 | tr '\n' ' ')"
printf '%s\n' "$TAG" > "$VFILE"

# ------------------------------------------- 10. INSTALL.json: what this IS
# FLAVOR used to be computed and thrown away, so no report could state whether
# its numbers were CUDA, Vulkan, Metal or CPU -- rule 3's strongest condition,
# unrecorded. Written here, the moment it is known (rule 28).
TOOLS_JSON=""
for t in ${TOOLS_BUILT:-}; do TOOLS_JSON="${TOOLS_JSON:+$TOOLS_JSON, }$(json_str "$t")"; done
{
  printf '{\n'
  printf '  "tag": %s,\n'                    "$(json_str "$TAG")"
  printf '  "flavor": %s,\n'                 "$(json_str "$FLAVOR")"
  printf '  "arch": %s,\n'                   "$(json_str "$ARCH")"
  printf '  "os": %s,\n'                     "$(json_str "$OS_TOKEN")"
  printf '  "os_version": %s,\n'             "$(json_str "$OS_DESC")"
  printf '  "host": %s,\n'                   "$(json_str "$(uname -n 2>/dev/null || printf unknown)")"
  printf '  "assets": [%s],\n'               "$ASSETS_JSON"
  printf '  "urls": [%s],\n'                 "$URLS_JSON"
  printf '  "installed_utc": %s,\n'          "$(json_str "$(date -u +%Y-%m-%dT%H:%M:%SZ)")"
  printf '  "built_from_source": %s,\n'      "$BUILT"
  if [ "$BUILT" = true ]; then
    printf '  "cuda_arch": %s,\n'            "$(json_str "$CUDA_ARCH")"
  else
    printf '  "cuda_arch": null,\n'
  fi
  printf '  "gpu": %s,\n'                    "$(json_str "$GPU")"
  printf '  "gpu_name": %s,\n'               "$(json_or_null "$GPU_NAME")"
  printf '  "driver_version": %s,\n'         "$(json_or_null "$DRIVER")"
  printf '  "server_version": %s,\n'         "$(json_str "$VER_OUT")"
  printf '  "source_commit": %s,\n'          "$(json_or_null "$SOURCE_COMMIT")"
  printf '  "build_seconds": %s,\n'          "${BUILD_SECONDS:-null}"
  printf '  "tools": [%s],\n'                "$TOOLS_JSON"
  printf '  "needs_ld_library_path": %s,\n'  "$NEEDS_LD_PATH"
  printf '  "vulkan_override": %s,\n'        "$([ "$ALLOW_VULKAN" = 1 ] && echo true || echo false)"
  case "$FROZEN_STATE" in
    match)     printf '  "frozen_inputs_match_commit": true,\n' ;;
    rewritten) printf '  "frozen_inputs_match_commit": false,\n' ;;
    *)         printf '  "frozen_inputs_match_commit": null,\n' ;;
  esac
  printf '  "installed_by": "scripts/setup.sh"\n'
  printf '}\n'
} > "$INSTALL_JSON"
info "Recorded $INSTALL_JSON"

# ------------------------------------------------------------ 11. Python venv
VENV_PY=""; REQ=""
setup_venv() {
  local c py="" vpy
  for c in python3 python3.12 python3.11 python3.10 python; do
    # a candidate that cannot run `import sys` is the Windows Store stub, not Python
    if have "$c" && "$c" -c 'import sys; assert sys.version_info >= (3, 10)' >/dev/null 2>&1; then
      py="$(command -v "$c")"; break
    fi
  done
  [ -n "$py" ] || die "no working Python 3.10+ found, and every collection script in this repo is Python.
       Ubuntu: sudo apt-get install -y python3 python3-venv python3-pip
       Then re-run, or pass --no-venv if you manage Python yourself." 6
  vpy="$ROOT/.venv/bin/python"; [ -x "$vpy" ] || vpy="$ROOT/.venv/Scripts/python.exe"
  if [ ! -x "$vpy" ]; then
    info "Creating $ROOT/.venv with $py..."
    "$py" -m venv "$ROOT/.venv" || die "python -m venv failed. Ubuntu: sudo apt-get install -y python3-venv" 6
    vpy="$ROOT/.venv/bin/python"; [ -x "$vpy" ] || vpy="$ROOT/.venv/Scripts/python.exe"
  fi
  [ -x "$vpy" ] || die "no interpreter under $ROOT/.venv after creating it." 6
  REQ="$ROOT/requirements-min.txt"; [ "$PUBLISH" = 1 ] && REQ="$ROOT/requirements.txt"
  [ -f "$REQ" ] || die "$REQ is missing." 6
  info "Installing $(basename "$REQ") into .venv..."
  "$vpy" -m pip install --disable-pip-version-check -r "$REQ" \
    || die "pip install -r $REQ failed. Offline? Re-run with --no-venv and install by hand." 6
  VENV_PY="$vpy"
}
if [ "$DO_VENV" = 1 ]; then setup_venv; else info "Skipping the .venv step (--no-venv)."; fi

# ----------------------------------------------------------------- 12. summary
echo ""
info "Done."
echo "  Release  : $TAG"
if [ "$BUILT" = true ]; then
  echo "  Flavor   : $FLAVOR  (built from source, CMAKE_CUDA_ARCHITECTURES=$CUDA_ARCH, commit ${SOURCE_COMMIT:-?}, ${BUILD_SECONDS}s)"
  echo "  Tools    : ${TOOLS_BUILT:-none}${TOOLS_MISSING:+   (not built: $TOOLS_MISSING)}"
else
  echo "  Flavor   : $FLAVOR  (official binary release)"
fi
echo "  Path     : $EXE"
echo "  Version  : $VER_OUT"
echo "  Record   : $INSTALL_JSON"
if [ "$DO_VENV" = 1 ]; then
  echo "  Python   : $VENV_PY  ($(basename "$REQ"))"
else
  echo "  Python   : not set up (--no-venv)"
fi
case "$FROZEN_STATE" in
  match)     echo "  Inputs   : frozen corpora + datasets match their committed bytes" ;;
  rewritten) echo "  Inputs   : REWRITTEN -- see the warning above; do not publish perplexity from this clone" ;;
  *)         echo "  Inputs   : NOT VERIFIED (no git metadata) -- check the corpora bytes by hand before publishing perplexity" ;;
esac
echo ""
echo "  Every number this build produces is a '$FLAVOR' number. Copy flavor, tag"
echo "  and driver from INSTALL.json into results/<slug>/campaign.md and into the"
echo "  report's conditions block -- rule 3; and rule 30's 'never compare across"
echo "  sweeps' starts with never comparing across backends."
