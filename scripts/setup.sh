#!/usr/bin/env bash
# Bootstrap a self-contained llama.cpp into <repo>/bin/llama.cpp/ -- no root, nothing outside the repo tree.
# Usage: ./setup.sh [-f|--force]
set -euo pipefail

# ---- Asset name patterns (grep -E, matched against browser_download_url basenames) -------------
# Verified against release b10582 (2026-08-22). Names drift between releases; fix here if selection fails.
# NOTE: NO official Linux CUDA binaries exist (checked b10582) -- NVIDIA x64 gets the Vulkan build
# (works on the NVIDIA driver) plus build-from-source guidance for native CUDA.
PAT_VULKAN_X64='llama-b[0-9]+-bin-ubuntu-vulkan-x64\.tar\.gz$'
PAT_CPU_X64='llama-b[0-9]+-bin-ubuntu-x64\.tar\.gz$'
PAT_CPU_ARM64='llama-b[0-9]+-bin-ubuntu-arm64\.tar\.gz$'        # official Linux ARM64 CPU build exists
PAT_VULKAN_ARM64='llama-b[0-9]+-bin-ubuntu-vulkan-arm64\.tar\.gz$'
PAT_MACOS_ARM64='llama-b[0-9]+-bin-macos-arm64\.tar\.gz$'       # Apple Silicon: Metal built in
PAT_MACOS_X64='llama-b[0-9]+-bin-macos-x64\.tar\.gz$'           # Intel Mac: CPU-only
TAG_RE='^b[0-9]+$'  # binary releases are tagged bNNNNN; /releases/latest points elsewhere (v0.2.0 nightly tracker)
# ------------------------------------------------------------------------------------------------

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
DEST="$ROOT/bin/llama.cpp"; DL="$DEST/.downloads"; VFILE="$DEST/VERSION.txt"; EXE="$DEST/llama-server"
FORCE=0; if [ "${1:-}" = "-f" ] || [ "${1:-}" = "--force" ]; then FORCE=1; fi

cuda_guidance() {
  cat <<'EOF'
[setup] NVIDIA GPU detected but there are NO official Linux CUDA binaries (any arch).
[setup] To build a CUDA llama-server from source (works on x64 and ARM64, e.g. DGX Spark GB10):
    git clone --depth 1 https://github.com/ggml-org/llama.cpp /tmp/llama.cpp && cd /tmp/llama.cpp
    cmake -B build -DGGML_CUDA=ON -DCMAKE_CUDA_ARCHITECTURES=native -DCMAKE_BUILD_TYPE=Release
    cmake --build build --config Release -j "$(nproc)" --target llama-server
    cp build/bin/llama-server* <repo>/bin/llama.cpp/
[setup] (On DGX Spark, if 'native' fails: -DCMAKE_CUDA_ARCHITECTURES=121. Requires cuda-toolkit + cmake.)
EOF
}

# 1. Detect OS + arch + GPU vendor
OS="$(uname -s)"; ARCH="$(uname -m)"; GPU="none"
if [ "$OS" = "Darwin" ]; then
  case "$ARCH" in
    arm64)  PAT="$PAT_MACOS_ARM64"; FLAVOR="metal"; GPU="apple" ;;  # Metal is built into the official arm64 binary
    x86_64) PAT="$PAT_MACOS_X64";   FLAVOR="cpu" ;;                 # Intel Mac: CPU-only official build
    *) echo "[setup] Unsupported macOS arch '$ARCH' -- build from source (cmake -B build && cmake --build build --target llama-server)." >&2; exit 1 ;;
  esac
else
  if command -v nvidia-smi >/dev/null 2>&1 && nvidia-smi -L >/dev/null 2>&1; then GPU="nvidia"
  elif command -v lspci >/dev/null 2>&1; then
    VGA="$(lspci 2>/dev/null | grep -iE 'vga|3d controller' || true)"
    case "$VGA" in *[Ii]ntel*|*AMD*|*ATI*) GPU="vulkan-capable";; esac
  fi
  case "$ARCH" in
    x86_64)  if [ "$GPU" = "none" ]; then PAT="$PAT_CPU_X64"; FLAVOR="cpu"; else PAT="$PAT_VULKAN_X64"; FLAVOR="vulkan"; fi ;;
    aarch64) if [ "$GPU" = "vulkan-capable" ]; then PAT="$PAT_VULKAN_ARM64"; FLAVOR="vulkan"; else PAT="$PAT_CPU_ARM64"; FLAVOR="cpu"; fi ;;
    *) echo "[setup] Unsupported arch '$ARCH' -- no official binaries; build from source." >&2; exit 1 ;;
  esac
fi
if [ "$GPU" = "nvidia" ]; then cuda_guidance; echo "[setup] Installing the '$FLAVOR' binary as a usable fallback."; fi
echo "[setup] arch=$ARCH gpu=$GPU -> flavor=$FLAVOR"

# 2. Find the newest bNNNNN release via the GitHub API (no jq dependency)
JSON="$(curl -fsSL -H 'User-Agent: measured-inference-setup' -H 'Accept: application/vnd.github+json' \
  'https://api.github.com/repos/ggml-org/llama.cpp/releases?per_page=10')"
TAG="$(printf '%s' "$JSON" | grep -oE '"tag_name": *"[^"]+"' | cut -d'"' -f4 | grep -E "$TAG_RE" | head -1)"
[ -n "$TAG" ] && echo "[setup] Latest binary release: $TAG" || { echo "[setup] No bNNNNN release found -- check TAG_RE." >&2; exit 1; }

# 3. Idempotency
if [ "$FORCE" -eq 0 ] && [ -f "$VFILE" ] && [ -x "$EXE" ] && [ "$(head -n1 "$VFILE" | tr -d '[:space:]')" = "$TAG" ]; then
  echo "[setup] $TAG already installed at $DEST -- nothing to do (use -f to redownload)."; exit 0
fi

# 4. Pick the asset URL for this release by pattern
URL="$(printf '%s' "$JSON" | grep -oE '"browser_download_url": *"[^"]+"' | cut -d'"' -f4 \
       | grep "/download/$TAG/" | grep -E "$PAT" | head -1)"
[ -n "$URL" ] || { echo "[setup] No asset in $TAG matches '$PAT' -- naming drifted; update patterns at top." >&2; exit 1; }
FILE="$DL/$(basename "$URL")"

# 5. Download (resumable) and extract (tarball has a llama-<tag>/ top dir -> strip it)
mkdir -p "$DEST" "$DL"
echo "[setup] Downloading $(basename "$URL")..."
curl -fL -C - --retry 3 --retry-delay 2 -o "$FILE" "$URL" || curl -fL --retry 3 -o "$FILE" "$URL"
echo "[setup] Extracting into $DEST..."
tar -xzf "$FILE" --strip-components=1 -C "$DEST"
rm -f "$FILE"

# 6. Verify llama-server exists and runs
[ -x "$EXE" ] || { echo "[setup] llama-server not found in $DEST after extraction." >&2; exit 1; }
VER_OUT="$(LD_LIBRARY_PATH="$DEST" DYLD_LIBRARY_PATH="$DEST" "$EXE" --version 2>&1)" \
  || { echo "[setup] llama-server --version failed: $VER_OUT" >&2; exit 1; }
VER_OUT="$(printf '%s\n' "$VER_OUT" | head -n2)"
printf '%s\n' "$TAG" > "$VFILE"

# 7. Summary
echo ""
echo "[setup] Done."
echo "  Release : $TAG"
echo "  Flavor  : $FLAVOR ($(basename "$URL"))"
echo "  Path    : $EXE"
echo "  Version : $VER_OUT"
if [ "$GPU" = "nvidia" ]; then echo "  Note    : CUDA needs a source build -- guidance printed above."; fi
