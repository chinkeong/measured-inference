#!/usr/bin/env bash
# Bootstrap a self-contained llama.cpp into <repo>/bin/llama.cpp/ -- no root,
# nothing outside the repo tree -- plus the Python venv the harness runs in.
#
#   ./scripts/setup.sh --cuda     # NVIDIA: build CUDA from source (the measuring path)
#   ./scripts/setup.sh --openvino # Intel CPU / iGPU / Arc / NPU: OpenVINO runtime + backend
#   ./scripts/setup.sh            # AMD / Apple / CPU: official binary release
#   ./scripts/setup.sh --check-npu   # Intel NPU prerequisites only; installs nothing
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
# WHAT --openvino INSTALLS, AND THE ONE THING IT CANNOT MAKE GO AWAY
# The OpenVINO backend is in mainline llama.cpp (ggml/src/ggml-openvino/, merged
# 2026-03-14) and reads GGUF directly, no conversion. It needs the OpenVINO
# RUNTIME, which is not the apt package: the pinned tarball goes to
# /opt/intel/openvino_<version> with an /opt/intel/openvino symlink, so the
# active version is swappable and every report can name the one that ran.
#
# What no flag changes: the backend REQUANTISES the file before it runs it
# (ggml-openvino-extra.cpp:252-273, read 2026-08-29). token_embd and output are
# rewritten on every device; on NPU every other quantized tensor becomes
# Q4_0_128 whatever it was on disk, so Q8_0, Q6_K, Q5_K, Q4_K_M and Q4_1 all
# collapse to one representation and a quant ladder on NPU compares arms that
# are the same weights. It is silent: the four log lines that would report a
# tensor changing type are commented out at ggml-openvino.cpp:332-346. So the
# file on disk is not the weights that ran (rule 3), and an OpenVINO arm is not
# comparable to a CUDA one (rule 30). This script records both facts in
# INSTALL.json rather than letting a campaign discover them at publication.
#
# WHY DGX SPARK IS SPECIAL-CASED
# GB10 is sm_121 with 128 GB of UNIFIED memory. -DCMAKE_CUDA_ARCHITECTURES must
# be 121a-real: 120, 120f and native all build, run, and quietly lose
# MMVQ_PARAMETERS_GB10, so the popular workaround produces a slower machine and
# no error. This script refuses those values on a GB10 instead.
#
# Exit codes: 2 usage . 3 backend/toolchain refusal . 4 install or verify failed
#             5 frozen inputs mangled (CRLF) . 6 Python/venv unusable
#             7 NPU prerequisites missing (--check-npu)
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

# ---- OpenVINO: runtime tarball + the llama.cpp asset built against it ---------------------------
# MEASURED 2026-08-29 by ranged HTTP reads against storage.openvinotoolkit.org and the
# GitHub releases API. The prebuilt llama.cpp asset carries the OpenVINO version in its
# NAME, so the asset pattern is built from OV_VERSION: a runtime/binary version mismatch
# is an ABI mismatch, and the coupling has to be visible rather than assumed.
OV_VERSION='2026.3.1'
OV_BUILD='2026.3.1.22476.56d9685302d'          # the full string ov::get_openvino_version() reports
OV_BASE='https://storage.openvinotoolkit.org/repositories/openvino/packages'
# Patch releases live in their OWN directory: .../packages/2026.3.1/linux/, not 2026.3/.
# The 2026.3/ path answers 200 with an HTML directory page, so a wrong prefix does not
# 404 -- it downloads a web page named .tgz. Verified both ways 2026-08-29.
OV_UBUNTU24_SHA256='cb84d1ccdecb8bd90337edf63e8d081a17cde2fc72f5e9feb213b5b2f96eb21b'
OV_UBUNTU22_SHA256='36576cee74f84e3986a659305fcd81ffedb629e56d4d4acff875f9008daed9f4'
OV_UBUNTU24_BYTES='110961409'
OV_PREFIX_DEFAULT='/opt/intel'
OV_DEVICES='CPU GPU NPU GPU.0 GPU.1'
# Intel NPU user-space driver. Ubuntu 24.04 ONLY -- linux-npu-driver dropped 22.04 at
# v1.28.0. Tag, asset name and publish date read from the GitHub API 2026-08-29.
NPU_DRIVER_TAG='v1.35.0'
NPU_DRIVER_DATE='2026-07-24'
NPU_DRIVER_ASSET='linux-npu-driver-v1.35.0.20260722-29947505341-ubuntu2404.tar.gz'
NPU_DRIVER_URL="https://github.com/intel/linux-npu-driver/releases/tag/$NPU_DRIVER_TAG"
# DGX Spark. 121a-real is not a preference: 120 / 120f / native all compile and lose
# MMVQ_PARAMETERS_GB10, which is a silent performance regression, not a build error.
GB10_CUDA_ARCH='121a-real'
# Built from OV_VERSION on purpose -- see above. Verified present on b10675..b10679.
PAT_OPENVINO_X64="llama-b[0-9]+-bin-ubuntu-openvino-${OV_VERSION//./[.]}-x64[.]tar[.]gz\$"
# ------------------------------------------------------------------------------------------------
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
      --cuda-arch A  value for -DCMAKE_CUDA_ARCHITECTURES (default: native, except
                     on a DGX Spark GB10, where it is 121a-real and 120/120f/
                     native are REFUSED -- they lose MMVQ_PARAMETERS_GB10)
      --openvino     Intel CPU / iGPU / Arc / NPU: install the pinned OpenVINO
                     RUNTIME tarball, then take the prebuilt llama.cpp OpenVINO
                     asset if the release has one, else build -DGGML_OPENVINO=ON
      --openvino-source     skip the prebuilt asset; always build from source
      --openvino-device D   CPU | GPU | NPU | GPU.0 | GPU.1 (default CPU).
                     Recorded, and exported as GGML_OPENVINO_DEVICE by launchers
      --openvino-dir P      install prefix for the runtime (default /opt/intel;
                     point it inside the repo on a box where you have no root)
      --openvino-version V  runtime version to install (default 2026.3.1).
                     Requires --openvino-build: the full build string is part of
                     the filename and is not derivable from the version
      --openvino-build S    full build string, e.g. 2026.3.1.22476.56d9685302d.
                     Only the pinned default carries a checksum verified here
      --skip-openvino-runtime  an OpenVINO runtime is already installed; use
                     --openvino-dir to say where, and it is recorded as CITED
      --check-npu    check the Intel NPU prerequisites and exit. Installs
                     nothing, downloads nothing, needs no GPU. Exit 7 if unmet
      --tag bNNNNN   pin a llama.cpp release instead of taking the newest one.
                     Pin it when a rerun must match an earlier campaign's build
      --publish      install requirements.txt (plots/stats) instead of requirements-min.txt
      --no-venv      skip the .venv step entirely (you manage Python yourself)
      --allow-vulkan accept a non-CUDA backend on an NVIDIA GPU (see below)
      --dry-run      detect, decide and print the plan; touch nothing, download nothing
  -h, --help         this text

Environment:
  MEASURED_INFERENCE_BUILD_CUDA=1     same as --cuda
  MEASURED_INFERENCE_BUILD_OPENVINO=1 same as --openvino
  MEASURED_INFERENCE_ALLOW_VULKAN=1   same as --allow-vulkan
  MEASURED_INFERENCE_CUDA_ARCH=...    same as --cuda-arch
  MEASURED_INFERENCE_ALLOW_CUDA_ARCH=1  build a GB10 with a refused -cuda-arch anyway,
                                      deliberately and recorded as an override
  MEASURED_INFERENCE_OPENVINO_DEVICE=D  same as --openvino-device
  MEASURED_INFERENCE_OPENVINO_DIR=P   same as --openvino-dir
  MEASURED_INFERENCE_ALLOW_CRLF=1     proceed even if a frozen input no longer matches its
                                      committed bytes (usually CRLF rewriting)
  MEASURED_INFERENCE_DRY_RUN=1        same as --dry-run (the gpu_lock convention)
  CUDA_HOME / CUDA_PATH               searched for bin/nvcc when nvcc is not on PATH

On an NVIDIA GPU, any backend other than CUDA changes every throughput number for
a reason unrelated to the model, so setup EXITS NON-ZERO rather than installing
one quietly. Either build CUDA (--cuda) or say --allow-vulkan and accept that
those numbers are not comparable to a CUDA campaign.

OpenVINO REQUANTISES the file before it runs it, on every device, and says
nothing. On NPU every quantized tensor other than token_embd and output becomes
Q4_0_128 whatever the file held, so a quant ladder there compares identical
weights. --openvino records this in INSTALL.json; read it before designing a
sweep (rule 3, rule 30).
USAGE
}

# ---------------------------------------------------------------- 0. arguments
FORCE=0; WANT_CUDA="${MEASURED_INFERENCE_BUILD_CUDA:-0}"; PUBLISH=0; DO_VENV=1
DRY="${MEASURED_INFERENCE_DRY_RUN:-0}"
ALLOW_VULKAN="${MEASURED_INFERENCE_ALLOW_VULKAN:-0}"
ALLOW_CRLF="${MEASURED_INFERENCE_ALLOW_CRLF:-0}"
ALLOW_CUDA_ARCH="${MEASURED_INFERENCE_ALLOW_CUDA_ARCH:-0}"
# CUDA_ARCH_SOURCE travels with the value because "native" as a default and
# "native" because the operator typed it are different facts on a GB10: the
# first is corrected to 121a-real, the second is refused.
CUDA_ARCH="${MEASURED_INFERENCE_CUDA_ARCH:-native}"
CUDA_ARCH_SOURCE=default
[ -n "${MEASURED_INFERENCE_CUDA_ARCH:-}" ] && CUDA_ARCH_SOURCE=env
WANT_OPENVINO="${MEASURED_INFERENCE_BUILD_OPENVINO:-0}"
OV_FORCE_SOURCE=0; OV_SKIP_RUNTIME=0; CHECK_NPU_ONLY=0
OV_VERSION_MOVED=0; OV_BUILD_MOVED=0
OV_DEVICE="${MEASURED_INFERENCE_OPENVINO_DEVICE:-CPU}"
OV_PREFIX="${MEASURED_INFERENCE_OPENVINO_DIR:-$OV_PREFIX_DEFAULT}"
TAG=""; TAG_PINNED=0
while [ $# -gt 0 ]; do
  case "$1" in
    -f|--force)      FORCE=1 ;;
    --cuda)          WANT_CUDA=1 ;;
    --cuda-arch)     CUDA_ARCH="${2:?--cuda-arch needs a value}"; CUDA_ARCH_SOURCE=flag; shift ;;
    --openvino)      WANT_OPENVINO=1 ;;
    --openvino-source) WANT_OPENVINO=1; OV_FORCE_SOURCE=1 ;;
    --openvino-device) OV_DEVICE="${2:?--openvino-device needs a value}"; shift ;;
    --openvino-dir)  OV_PREFIX="${2:?--openvino-dir needs a value}"; shift ;;
    --openvino-version) OV_VERSION="${2:?--openvino-version needs a value}"; OV_VERSION_MOVED=1; shift ;;
    --openvino-build)   OV_BUILD="${2:?--openvino-build needs a value}"; OV_BUILD_MOVED=1; shift ;;
    --skip-openvino-runtime) OV_SKIP_RUNTIME=1 ;;
    --check-npu)     CHECK_NPU_ONLY=1 ;;
    --tag)           TAG="${2:?--tag needs a value}"; TAG_PINNED=1; shift ;;
    --publish)       PUBLISH=1 ;;
    --no-venv)       DO_VENV=0 ;;
    --allow-vulkan|--allow-non-cuda) ALLOW_VULKAN=1 ;;
    --dry-run)       DRY=1 ;;
    -h|--help)       usage; exit 0 ;;
    *) usage >&2; die "unknown option '$1'" 2 ;;
  esac
  shift
done
if [ "$TAG_PINNED" -eq 1 ] && ! printf '%s' "$TAG" | grep -qE "$TAG_RE"; then
  die "--tag '$TAG' does not look like a llama.cpp binary release (bNNNNN)." 2
fi
if [ "$WANT_CUDA" = 1 ] && [ "$WANT_OPENVINO" = 1 ]; then
  die "--cuda and --openvino are two different backends and therefore two different experiments (rule 30). Pick one; run the other into a second checkout." 2
fi
# The asset name carries the runtime version, so re-derive the pattern if
# --openvino-version moved it. A 2026.3.1 binary against a 2026.4 runtime is an
# ABI gamble, not a fallback.
PAT_OPENVINO_X64="llama-b[0-9]+-bin-ubuntu-openvino-${OV_VERSION//./[.]}-x64[.]tar[.]gz\$"
if [ "$WANT_OPENVINO" = 1 ]; then
  case " $OV_DEVICES " in
    *" $OV_DEVICE "*) ;;
    *) die "--openvino-device '$OV_DEVICE' is not one of: $OV_DEVICES (GGML_OPENVINO_DEVICE, ggml-openvino.cpp)." 2 ;;
  esac
fi
# Checked here rather than at install time so --dry-run catches it too: a plan
# printed with the pinned build string under a version the operator moved would
# name a file that does not exist.
if [ "$OV_VERSION_MOVED" = 1 ] && [ "$OV_BUILD_MOVED" = 0 ]; then
  die "--openvino-version $OV_VERSION without --openvino-build: the full build string (the default is $OV_BUILD) is part of the tarball filename and cannot be derived from the version. Read it off $OV_BASE/$OV_VERSION/linux/ and pass it. Note that no checksum in this script covers a build other than the pinned one." 2
fi
[ "$DRY" = 1 ] && info "DRY RUN: nothing is downloaded, built, written or installed."

# ----------------------------------- 0b. Intel silicon and the NPU prerequisites
# A CHECK AND A MESSAGE, never an install. The NPU driver needs root, a kernel
# module and usually a reboot; a setup script that half-installs it leaves a box
# in a state nobody can describe afterwards. What this buys is the timing: a
# campaign learns on minute one that its NPU cannot run, instead of finding out
# when the plugin segfaults eight hours in.
#
# The classification defaults to CAUTION. Only an affirmative Lunar Lake or
# Panther Lake match clears the NPU; an unrecognised part warns, because the
# expensive mistake here is a false all-clear on an Arrow Lake, not a spurious
# warning on a part this table has not met.
CPU_GEN=unknown; CPU_MODEL_NAME=""; CPU_CPUID=""
CPU_GEN_WHY="not looked at"
NPU_STATUS=not-checked
NPU_FINDINGS=()
npu_find() { NPU_FINDINGS+=("$1"); }

detect_intel_cpu_gen() {
  local name num suffix fam mod
  if [ ! -r /proc/cpuinfo ]; then
    CPU_GEN=unknown; CPU_GEN_WHY="/proc/cpuinfo is not readable here (not Linux?)"; return 0
  fi
  name="$(grep -m1 -E '^model name' /proc/cpuinfo | cut -d: -f2- | sed 's/^ *//; s/ *$//' || true)"
  fam="$(grep -m1 -E '^cpu family' /proc/cpuinfo | cut -d: -f2- | tr -d '[:space:]' || true)"
  mod="$(grep -m1 -E '^model[[:space:]]*:' /proc/cpuinfo | cut -d: -f2- | tr -d '[:space:]' || true)"
  CPU_MODEL_NAME="$name"; CPU_CPUID="${fam:-?}/${mod:-?}"
  case "$name" in
    *Intel*) ;;
    *) CPU_GEN=non-intel
       CPU_GEN_WHY="the model name is not an Intel part: ${name:-unreadable}"; return 0 ;;
  esac
  # Classify on the MARKETING model number, which is the identity Intel
  # publishes and a reader can check against the sticker. The cpuid family/model
  # pair is printed beside it as evidence, not used as the rule: a wrong cpuid
  # mapping here would produce exactly the false all-clear this exists to stop.
  # X? because Panther Lake brands a tier as "Core Ultra X7 358H" alongside
  # "Core Ultra 7 355H"; without it an X-tier part reads as pre-Ultra silicon,
  # and this script would tell a Panther Lake owner they have no NPU.
  num="$(printf '%s' "$name" | grep -oE 'Ultra +X?[0-9]+ +[0-9]{3}[A-Za-z]*' | head -1 | awk '{print $NF}' || true)"
  if [ -z "$num" ]; then
    CPU_GEN=pre-ultra
    CPU_GEN_WHY="an Intel part with no 'Core Ultra NNN' model number carries no NPU: ${name:-unreadable}"
    return 0
  fi
  suffix="$(printf '%s' "$num" | tr -d '0-9' | tr '[:lower:]' '[:upper:]')"
  case "$num" in
    3??*) CPU_GEN=panther-lake
          CPU_GEN_WHY="Core Ultra series 3 ($num) is Panther Lake" ;;
    2??*) if [ "$suffix" = "V" ]; then
            CPU_GEN=lunar-lake
            CPU_GEN_WHY="Core Ultra series 2 with a V suffix ($num) is Lunar Lake"
          else
            CPU_GEN=arrow-lake
            CPU_GEN_WHY="Core Ultra series 2 without a V suffix ($num) is Arrow Lake"
          fi ;;
    1??*) CPU_GEN=meteor-lake
          CPU_GEN_WHY="Core Ultra series 1 ($num) is Meteor Lake" ;;
    *)    CPU_GEN=unknown
          CPU_GEN_WHY="model number '$num' matches no Core Ultra series this script knows" ;;
  esac
}

check_npu_prereqs() {
  local ver_id="" mod_ver="" node
  detect_intel_cpu_gen
  echo ""
  info "--- Intel NPU prerequisites (checked, never installed) ---"
  info "CPU        : ${CPU_MODEL_NAME:-unknown}   (cpuid family/model ${CPU_CPUID:-?/?})"
  info "Silicon    : $CPU_GEN -- $CPU_GEN_WHY"

  case "$CPU_GEN" in
    arrow-lake)
      npu_find "Arrow Lake: the NPU SIGSEGVs inside libopenvino_intel_npu_plugin.so (Intel engineer, 2026-07-21, still open)"
      warn "ARROW LAKE NPU IS BROKEN. It is not a configuration problem and there is no flag for it."
      cat >&2 <<'ARROWLAKE'
[setup]        The OpenVINO NPU plugin SIGSEGVs on Arrow Lake -- confirmed by an
[setup]        Intel engineer on 2026-07-21 and still open. Lunar Lake and Panther
[setup]        Lake work. A campaign that points its arms at this NPU loses the day
[setup]        and produces nothing, so run the Intel arms on GPU or CPU here:
[setup]            ./scripts/setup.sh --openvino --openvino-device GPU
ARROWLAKE
      ;;
    lunar-lake|panther-lake)
      info "NPU silicon: $CPU_GEN -- llama.cpp validates the OpenVINO NPU path on Core Ultra 5 238V (Lunar Lake), Ubuntu 24.04." ;;
    meteor-lake)
      npu_find "Meteor Lake NPU: present, but the OpenVINO NPU path is validated on Lunar Lake, not here"
      warn "Meteor Lake has an NPU, but llama.cpp's validated OpenVINO NPU box is Lunar Lake. Treat any NPU number from this part as unvalidated and say so (rule 1)." ;;
    pre-ultra|non-intel)
      npu_find "no NPU silicon: $CPU_GEN_WHY"
      warn "This part has no NPU. Use --openvino-device CPU or GPU." ;;
    *)
      npu_find "silicon generation unidentified, so the Arrow Lake exclusion cannot be checked"
      warn "Could not identify the silicon generation, so this script cannot tell you whether the Arrow Lake segfault applies. Check the model number by hand before spending an hour." ;;
  esac

  if [ -r /etc/os-release ]; then
    ver_id="$(grep -m1 -E '^VERSION_ID=' /etc/os-release | cut -d= -f2- | tr -d '"' || true)"
  fi
  info "Distro     : ${ver_id:-unknown} (linux-npu-driver ships an ubuntu2404 asset only)"
  case "$ver_id" in
    24.04) ;;
    "")    npu_find "Ubuntu release unknown -- /etc/os-release carries no VERSION_ID" ;;
    22.04) npu_find "Ubuntu 22.04: linux-npu-driver dropped it at v1.28.0; $NPU_DRIVER_TAG ships ubuntu2404 only" ;;
    *)     npu_find "Ubuntu $ver_id is not 24.04, which is the only release $NPU_DRIVER_TAG publishes an asset for" ;;
  esac

  if [ -d /sys/module/intel_vpu ]; then
    [ -r /sys/module/intel_vpu/version ] && mod_ver="$(cat /sys/module/intel_vpu/version 2>/dev/null || true)"
    info "Kernel mod : intel_vpu loaded${mod_ver:+ (version $mod_ver)}"
  else
    npu_find "the intel_vpu kernel module is not loaded (no /sys/module/intel_vpu)"
    warn "intel_vpu is not loaded. It is in-tree from Linux 6.7; on Ubuntu 24.04 check 'modprobe intel_vpu' and 'dmesg | grep -i vpu'."
  fi

  node=""
  for node in /dev/accel/accel0 /dev/accel/accel1 ""; do
    [ -n "$node" ] && [ -e "$node" ] && break
  done
  if [ -n "$node" ]; then
    if [ -r "$node" ] && [ -w "$node" ]; then
      info "Device node: $node readable and writable by $(id -un 2>/dev/null || echo "$USER")"
    else
      npu_find "$node exists but this user cannot open it -- add yourself to the 'render' group and log in again"
      warn "$node is not readable/writable here: sudo usermod -a -G render \$USER, then log out and back in."
    fi
  else
    npu_find "no /dev/accel/accelN device node -- the NPU is not exposed to user space"
  fi

  if have ldconfig && ldconfig -p 2>/dev/null | grep -q 'libze_intel_vpu\.so'; then
    info "User driver: libze_intel_vpu.so found on the loader path"
  else
    npu_find "libze_intel_vpu.so is not on the loader path -- the intel/linux-npu-driver user-space packages are not installed"
  fi
  if have ldconfig && ldconfig -p 2>/dev/null | grep -q 'libze_loader\.so'; then
    info "Level Zero : libze_loader.so found"
  else
    npu_find "libze_loader.so is not on the loader path -- the Level Zero loader is missing"
  fi

  if [ "${#NPU_FINDINGS[@]}" -eq 0 ]; then
    NPU_STATUS=ok
    info "NPU        : prerequisites met."
  else
    NPU_STATUS=blocked
    echo "" >&2
    warn "NPU prerequisites NOT met -- ${#NPU_FINDINGS[@]} finding(s):"
    for node in "${NPU_FINDINGS[@]}"; do printf '[setup]   - %s\n' "$node" >&2; done
    cat >&2 <<NPUHELP
[setup]
[setup] The driver is a release tarball, not an apt package, and Ubuntu 24.04 is the
[setup] only release it publishes for -- 22.04 was dropped at v1.28.0:
[setup]     $NPU_DRIVER_URL
[setup]     asset: $NPU_DRIVER_ASSET   ($NPU_DRIVER_TAG, published $NPU_DRIVER_DATE)
[setup]     tar -xf $NPU_DRIVER_ASSET
[setup]     sudo dpkg -i ./*.deb            # intel-driver-compiler-npu, intel-fw-npu, intel-level-zero-npu
[setup]     sudo apt-get install -y libtbb12
[setup]     sudo usermod -a -G render \$USER   # then log out and back in
[setup]     sudo reboot                      # if intel_vpu was not loaded
[setup] Re-run './scripts/setup.sh --check-npu' afterwards; it installs nothing.
NPUHELP
  fi
  echo ""
}

if [ "$CHECK_NPU_ONLY" = 1 ]; then
  check_npu_prereqs
  cat <<'NPURUN'
[setup] Three NPU run-time conditions that are not prerequisites and will not show up
[setup] in any check, but will change your numbers:
[setup]   - llama-server on NPU needs an EXPLICIT -c. Without one it takes the
[setup]     model's training context, which is usually far larger than you meant and
[setup]     changes both the fit and the speed (rule 3: the window travels with the
[setup]     number; rule 16: the window sets the effort ceiling).
[setup]   - llama-server on NPU cannot handle parallel sequences: --parallel 1 only.
[setup]   - Every quantized tensor other than token_embd and output is rewritten to
[setup]     Q4_0_128 on NPU, whatever the file holds. A quant ladder there compares
[setup]     arms that are the same weights (rule 30). Use CPU or GPU for a ladder.
NPURUN
  [ "$NPU_STATUS" = ok ] && exit 0
  exit 7
fi

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
COMPUTE_CAP=""; GB10=0; GB10_WHY=""
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
    COMPUTE_CAP="$(nvidia-smi --query-gpu=compute_cap --format=csv,noheader 2>/dev/null | head -1 | tr -d '[:space:]' || true)"
    # DGX Spark. Two independent signals, either one enough (rule 4): the board
    # name, and compute capability 12.1, which no other shipping part reports.
    case "$GPU_NAME" in *GB10*|*"DGX Spark"*) GB10=1; GB10_WHY="nvidia-smi board name '$GPU_NAME'" ;; esac
    if [ "$GB10" = 0 ] && [ "$COMPUTE_CAP" = "12.1" ]; then
      GB10=1; GB10_WHY="nvidia-smi compute_cap 12.1 (sm_121)"
    fi
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
# --openvino replaces the candidate list rather than extending it. There is no
# "openvino, else cpu" fallback on purpose: a CPU asset installed because the
# OpenVINO one was missing is the silent backend substitution section 4 refuses,
# and it would be recorded as an openvino campaign.
if [ "$WANT_OPENVINO" = 1 ]; then
  case "$ARCH" in
    x86_64|amd64) PAT_LIST="openvino:$PAT_OPENVINO_X64" ;;
    *) die "--openvino on '$ARCH': the OpenVINO runtime tarball and the llama.cpp OpenVINO asset are both x86_64-only at $OV_VERSION (checked 2026-08-29). No arm64 build exists to install." 3 ;;
  esac
fi
FLAVOR="${PAT_LIST%%:*}"   # intended flavor; the asset that actually matches decides
info "os=$OS arch=$ARCH gpu=$GPU${GPU_NAME:+ ($GPU_NAME, driver $DRIVER)}${COMPUTE_CAP:+ compute_cap=$COMPUTE_CAP}"
[ "$GB10" = 1 ] && info "DGX Spark GB10 detected: $GB10_WHY"

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
TOOLS_BUILT=""; TOOLS_MISSING=""; CUDA_ARCH_OVERRIDE=0
OV_ROOT=""; OV_LIBDIR=""; OV_INSTALL_PATH=""; OV_RUNTIME_SOURCE=""

# ------------------------------ 3a. the OpenVINO runtime: paths and installer
# The RUNTIME is what --openvino installs; the llama.cpp binaries -- prebuilt or
# built here -- are the small half. Both halves are needed either way: the
# prebuilt asset carries the OpenVINO version in its NAME because it links
# against that runtime and no other.
OV_SUDO=""; OV_UBUNTU=""; OV_TARBALL=""; OV_URL=""; OV_SHA256=""; OV_SHA_SOURCE=""
sha256_of() {
  if   have sha256sum; then sha256sum "$1" | awk '{print $1}'
  elif have shasum;    then shasum -a 256 "$1" | awk '{print $1}'
  else printf ''; fi
}
ov_paths() {
  # Ubuntu 24.04 is the default because it is what the prebuilt llama.cpp asset
  # is built for and the only release the NPU driver ships. 22.04 gets the 22
  # runtime so a CPU/GPU source build still works there -- but not the NPU.
  local ver_id=""
  [ -r /etc/os-release ] && ver_id="$(grep -m1 -E '^VERSION_ID=' /etc/os-release | cut -d= -f2- | tr -d '"' || true)"
  case "$ver_id" in
    22.04) OV_UBUNTU=ubuntu22 ;;
    *)     OV_UBUNTU=ubuntu24 ;;
  esac
  OV_TARBALL="openvino_toolkit_${OV_UBUNTU}_${OV_BUILD}_x86_64.tgz"
  OV_URL="$OV_BASE/$OV_VERSION/linux/$OV_TARBALL"
  OV_ROOT="$OV_PREFIX/openvino_$OV_VERSION"
  OV_LIBDIR="$OV_ROOT/runtime/lib/intel64"
}
ov_resolve_libdir() {
  # The documented layout is runtime/lib/intel64, but that is a claim about an
  # archive this script cannot inspect before downloading it. So the path above
  # is a first guess and this is the answer: find the directory that actually
  # holds libopenvino.so. A hard-coded path that drifts would fail at the first
  # server launch, hours later, instead of here.
  local hit
  [ -n "$OV_ROOT" ] && [ -d "$OV_ROOT" ] || return 0
  [ -d "$OV_LIBDIR" ] && return 0
  hit="$(find "$OV_ROOT" -maxdepth 6 -name 'libopenvino.so*' -type f 2>/dev/null | head -1 || true)"
  [ -n "$hit" ] && OV_LIBDIR="$(dirname "$hit")"
  return 0
}
ov_expected_sha() {
  # Only the pinned build has a checksum that was read here and written down.
  if [ "$OV_VERSION_MOVED" = 1 ] || [ "$OV_BUILD_MOVED" = 1 ]; then printf ''; return 0; fi
  case "$OV_UBUNTU" in
    ubuntu24) printf '%s' "$OV_UBUNTU24_SHA256" ;;
    ubuntu22) printf '%s' "$OV_UBUNTU22_SHA256" ;;
  esac
}
ov_prepare_prefix() {
  if [ "$(id -u)" = 0 ]; then OV_SUDO=""; return 0; fi
  if mkdir -p "$OV_PREFIX" 2>/dev/null && [ -w "$OV_PREFIX" ]; then OV_SUDO=""; return 0; fi
  if have sudo; then
    OV_SUDO=sudo
    if sudo -n true 2>/dev/null; then return 0; fi
    # A password prompt is fine for a human and fatal for an agent: the harness
    # runs this with no TTY, sudo blocks reading a password nobody can type,
    # and the run hangs rather than fails. The usual way this repo gets driven
    # is a clone plus a prompt to a coding agent, so refuse EARLY and name the
    # two ways out instead of stalling on a tty check nobody sees.
    if [ ! -t 0 ]; then
      die "$OV_PREFIX needs root and sudo would prompt for a password, but this
     is running without a terminal, so nothing can answer it. Either install
     where you already have write access, which needs no root at all:
         ./scripts/setup.sh --openvino --openvino-dir $ROOT/bin/openvino
     or have a human run this once, then re-run:
         sudo install -d -o \"\$USER\" $OV_PREFIX" 4
    fi
    info "$OV_PREFIX needs root; sudo will prompt."
    return 0
  fi
  die "cannot write $OV_PREFIX and there is no sudo here. Either install the runtime somewhere you own -- ./scripts/setup.sh --openvino --openvino-dir $ROOT/bin/openvino -- or have an administrator create $OV_PREFIX and chown it to you." 4
}
install_openvino_runtime() {
  local tgz sidecar got want staging
  ov_paths
  if [ "$OV_SKIP_RUNTIME" = 1 ]; then
    # CITED, not measured: the operator says a runtime is there, and the only
    # thing checked is that the library directory exists.
    OV_RUNTIME_SOURCE="pre-existing, --skip-openvino-runtime"
    ov_resolve_libdir
    [ -d "$OV_LIBDIR" ] || die "--skip-openvino-runtime, but no libopenvino.so was found anywhere under $OV_ROOT. Point --openvino-dir at the PREFIX that holds openvino_$OV_VERSION/, not at the runtime directory itself." 4
    info "OpenVINO runtime: using the existing $OV_ROOT, libraries at $OV_LIBDIR (nothing else about it is verified)."
    return 0
  fi
  if [ -d "$OV_LIBDIR" ] && [ "$FORCE" -eq 0 ]; then
    OV_RUNTIME_SOURCE="already present at $OV_ROOT"
    info "OpenVINO runtime $OV_VERSION already at $OV_ROOT -- keeping it (-f to reinstall)."
    return 0
  fi
  if [ "$OV_VERSION_MOVED" = 1 ] && [ "$OV_BUILD_MOVED" = 0 ]; then
    die "--openvino-version $OV_VERSION without --openvino-build: the full build string (e.g. $OV_BUILD) is part of the filename and cannot be derived from the version. Read it off the directory listing at $OV_BASE/$OV_VERSION/linux/ and pass it." 2
  fi
  ov_prepare_prefix
  mkdir -p "$DL"
  tgz="$DL/$OV_TARBALL"; sidecar="$DL/$OV_TARBALL.sha256"
  info "Downloading the OpenVINO $OV_VERSION runtime ($OV_UBUNTU, ~106 MiB)..."
  info "  $OV_URL"
  curl -fL -C - --retry 3 --retry-delay 2 -o "$tgz" "$OV_URL" || curl -fL --retry 3 -o "$tgz" "$OV_URL" \
    || die "download failed: $OV_URL
       Note the directory: patch releases live under packages/$OV_VERSION/, not packages/${OV_VERSION%.*}/. A wrong prefix there answers 200 with an HTML page, so check what landed before blaming the network." 4
  curl -fsSL -o "$sidecar" "$OV_URL.sha256" || true

  got="$(sha256_of "$tgz")"
  want="$(ov_expected_sha)"
  if [ -z "$got" ]; then
    warn "no sha256sum or shasum here, so the runtime tarball could not be checksummed. Install coreutils and re-run with -f if this build will publish numbers."
    OV_SHA256=""; OV_SHA_SOURCE="unverified: no sha256 tool on PATH"
  else
    OV_SHA256="$got"; OV_SHA_SOURCE="measured, sha256sum of the downloaded file"
    if [ -n "$want" ] && [ "$got" != "$want" ]; then
      die "OpenVINO runtime checksum mismatch.
       expected $want   (read from storage.openvinotoolkit.org 2026-08-29 and pinned in this script)
       got      $got
       Either the download is truncated or the published artefact changed. Delete $tgz and retry; if it persists, the pinned constant needs re-reading, and that is a finding, not a nuisance." 4
    fi
    if [ -s "$sidecar" ]; then
      local pub; pub="$(awk '{print $1}' "$sidecar" | head -1)"
      if [ -n "$pub" ] && [ "$pub" != "$got" ]; then
        die "the published .sha256 sidecar ($pub) does not match the file downloaded ($got)." 4
      fi
      [ -n "$want" ] || OV_SHA_SOURCE="measured, matches the published .sha256 sidecar (no pinned constant for this build)"
    elif [ -z "$want" ]; then
      warn "no pinned checksum for build $OV_BUILD and the .sha256 sidecar did not download. The runtime is UNVERIFIED; say so wherever its numbers appear."
      OV_SHA_SOURCE="unverified: no pinned constant and no sidecar"
    fi
  fi

  # --strip-components=1 into a staging directory: the tarball's top-level name
  # carries the full build string, and depending on it would be one more guess.
  staging="$DL/ov-staging.$$"
  rm -rf "$staging"; mkdir -p "$staging"
  info "Extracting to $OV_ROOT ..."
  tar -xzf "$tgz" --strip-components=1 -C "$staging" || die "extract failed: $tgz" 4
  find "$staging" -maxdepth 6 -name 'libopenvino.so*' -type f 2>/dev/null | head -1 | grep -q . \
    || die "the extracted archive contains no libopenvino.so -- this is not the OpenVINO runtime, or its layout changed. Nothing has been installed." 4
  $OV_SUDO rm -rf "$OV_ROOT"
  $OV_SUDO mkdir -p "$OV_PREFIX"
  $OV_SUDO mv "$staging" "$OV_ROOT" || die "could not move the extracted runtime into $OV_ROOT." 4
  # The symlink is the point of the versioned directory: /opt/intel/openvino is
  # what everything else names, and swapping versions is one ln -sfn.
  $OV_SUDO ln -sfn "$OV_ROOT" "$OV_PREFIX/openvino" || warn "could not create the $OV_PREFIX/openvino symlink; the versioned path still works."
  rm -f "$tgz" "$sidecar"
  OV_RUNTIME_SOURCE="$OV_URL"
  ov_resolve_libdir
  info "OpenVINO runtime $OV_VERSION installed: $OV_ROOT (active via $OV_PREFIX/openvino)"
  info "  libraries: $OV_LIBDIR"
}

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

  # ---- DGX Spark: the architecture flag is a measurement condition ------------
  # 120, 120f and native all configure, compile and run on a GB10. What they do
  # not do is keep MMVQ_PARAMETERS_GB10, so the box decodes slower for a reason
  # that is invisible at every later step -- no error, no log line, and until
  # now no field in any artefact. That is the exact shape of failure this repo
  # refuses (rule 3), so the popular workaround is a hard error, not a warning.
  if [ "$GB10" = 1 ]; then
    if [ "$CUDA_ARCH_SOURCE" = default ]; then
      CUDA_ARCH="$GB10_CUDA_ARCH"; CUDA_ARCH_SOURCE=gb10-default
      info "GB10: -DCMAKE_CUDA_ARCHITECTURES defaults to $GB10_CUDA_ARCH here, not 'native'."
    fi
    case "$CUDA_ARCH" in
      *121a*) info "GB10: -DCMAKE_CUDA_ARCHITECTURES=$CUDA_ARCH ($CUDA_ARCH_SOURCE) keeps MMVQ_PARAMETERS_GB10." ;;
      *)
        if [ "$ALLOW_CUDA_ARCH" = 1 ]; then
          CUDA_ARCH_OVERRIDE=1
          warn "GB10 with -DCMAKE_CUDA_ARCHITECTURES=$CUDA_ARCH (MEASURED_INFERENCE_ALLOW_CUDA_ARCH=1)."
          warn "This build loses MMVQ_PARAMETERS_GB10. Every decode number it produces is a different experiment from a 121a-real build; INSTALL.json records the override."
        else
          cat >&2 <<GB10GATE
[setup] ERROR: this is a DGX Spark GB10 ($GB10_WHY) and
[setup]        -DCMAKE_CUDA_ARCHITECTURES=$CUDA_ARCH ($CUDA_ARCH_SOURCE) is refused.
[setup]
[setup] 120, 120f and native are the workarounds that circulate, and they all build
[setup] and run. What they lose is MMVQ_PARAMETERS_GB10 -- the GB10 matrix-vector
[setup] kernel parameters. You get a working server that decodes slower, with no
[setup] error and nothing in the log to tell you, and no artefact in this repo would
[setup] have carried the flag that caused it.
[setup]
[setup] Build the architecture that keeps those kernels:
[setup]     ./scripts/setup.sh --cuda --cuda-arch $GB10_CUDA_ARCH
[setup]
[setup] Or take the slower kernels deliberately and on the record (INSTALL.json gets
[setup] cuda_arch_override: true, and no number from it is comparable to a
[setup] $GB10_CUDA_ARCH campaign -- rule 30):
[setup]     MEASURED_INFERENCE_ALLOW_CUDA_ARCH=1 ./scripts/setup.sh --cuda --cuda-arch $CUDA_ARCH
GB10GATE
          exit 3
        fi ;;
    esac
    warn "GB10 has 128 GB of UNIFIED memory and no discrete board. nvidia-smi VRAM sampling and the board_total_mib - reserve fit arithmetic both FAIL SILENTLY here -- see reference/platform-notes.md, 'DGX Spark reports VRAM that is not a board'. Do not let a fit ceiling (rule 13) be derived from them."
  fi
  FLAVOR="cuda"
  info "CUDA source build requested: nvcc=$NVCC arch=$CUDA_ARCH ($CUDA_ARCH_SOURCE)"
fi

# --------------------------------------------- 3b. OpenVINO: toolchain and gate
if [ "$WANT_OPENVINO" = 1 ]; then
  [ "$OS" = "Linux" ] || die "--openvino here targets Linux; on Windows use scripts\\setup.ps1 -OpenVINO (the win-openvino zip)." 3
  if [ "$OV_FORCE_SOURCE" = 1 ]; then
    have cmake || die "--openvino-source needs cmake: sudo apt-get install -y cmake build-essential git" 3
    have git   || die "--openvino-source needs git: sudo apt-get install -y git" 3
  fi
  FLAVOR="openvino"
  # Resolve OV_ROOT / OV_LIBDIR here, not inside the installer: an idempotent
  # re-run skips the install entirely, and the verify step still has to put the
  # runtime's library directory on the loader path or llama-server cannot start.
  ov_paths
  info "OpenVINO backend requested: runtime $OV_VERSION ($OV_BUILD), device $OV_DEVICE, prefix $OV_PREFIX"
  # Said once, before anything is downloaded, because it governs sweep DESIGN and
  # not just reporting: by the time a ladder has run, the money is spent.
  warn "OpenVINO REQUANTISES the file before it runs it, on every device, and logs nothing (ggml-openvino-extra.cpp:252-273; the four reporting lines are commented out at ggml-openvino.cpp:332-346, read 2026-08-29)."
  warn "  token_embd -> F16 on NPU from Q6_K, else Q8_0_C. output -> Q8_0_C. Always, any device."
  warn "  Q6_K and Q5_K -> Q8_0_C off NPU. Q8_0_C is CHANNEL-WISE (one scale per row), so that is more bits at COARSER scale granularity -- not an upgrade."
  if [ "$OV_DEVICE" = "NPU" ]; then
    warn "  ON NPU every other quantized tensor becomes Q4_0_128 whatever the file held -- Q8_0, Q5_K, Q6_K, Q4_K_M, Q4_1 all collapse to one representation, and even Q4_0 is re-blocked from 32 to 128 weights per block (four times fewer scales)."
    warn "  A QUANT LADDER ON THIS DEVICE IS DEGENERATE: the arms are the same weights (rule 30). Run the ladder on CPU or GPU, or drop it and say why."
    check_npu_prereqs
    if [ "$NPU_STATUS" != ok ]; then
      die "--openvino-device NPU, but the NPU prerequisites above are not met. Fix them, or pick a device that works here: --openvino-device GPU (or CPU)." 3
    fi
  fi
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
    if [ "$GB10" = 1 ]; then
      cat >&2 <<GB10NOTE
[setup]
[setup] This box is a DGX Spark GB10 ($GB10_WHY), where the source build is not one
[setup] option of two: there is no official Linux aarch64 CUDA binary at any release,
[setup] so nothing to fall back to. Build it, and take the architecture with it --
[setup] on GB10 the flag is not a default, it is a condition:
[setup]     ./scripts/setup.sh --cuda --cuda-arch $GB10_CUDA_ARCH
GB10NOTE
    fi
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

  # RPATH $ORIGIN so the binaries still find libggml*.so after being copied out
  # of build/bin into bin/llama.cpp/ -- callers Popen them directly, with no
  # LD_LIBRARY_PATH (scripts/bench/bench.py, scripts/lib/paths.py). The OpenVINO
  # runtime is the exception: it stays in its versioned prefix so it can be
  # swapped, so those libraries need an rpath entry of their own.
  if [ "$FLAVOR" = "openvino" ]; then
    info "Configuring: GGML_OPENVINO=ON OpenVINO_DIR=$OV_ROOT/runtime/cmake CMAKE_BUILD_TYPE=Release"
    cmake -S "$SRC" -B "$SRC/build" \
          -DGGML_OPENVINO=ON \
          -DOpenVINO_DIR="$OV_ROOT/runtime/cmake" \
          -DCMAKE_BUILD_TYPE=Release \
          -DLLAMA_BUILD_TESTS=OFF \
          -DCMAKE_BUILD_WITH_INSTALL_RPATH=ON \
          -DCMAKE_INSTALL_RPATH="\$ORIGIN;$OV_LIBDIR" \
      || die "cmake configure failed with -DGGML_OPENVINO=ON. Check that $OV_ROOT/runtime/cmake exists (that is what the runtime tarball provides) and that this llama.cpp tag is new enough -- the backend merged 2026-03-14, so a tag older than that has no ggml/src/ggml-openvino/ to build." 4
  else
    info "Configuring: GGML_CUDA=ON CMAKE_CUDA_ARCHITECTURES=$CUDA_ARCH CMAKE_BUILD_TYPE=Release"
    cmake -S "$SRC" -B "$SRC/build" \
          -DGGML_CUDA=ON \
          -DCMAKE_CUDA_ARCHITECTURES="$CUDA_ARCH" \
          -DCMAKE_CUDA_COMPILER="$NVCC" \
          -DCMAKE_BUILD_TYPE=Release \
          -DLLAMA_BUILD_TESTS=OFF \
          -DCMAKE_BUILD_WITH_INSTALL_RPATH=ON \
          -DCMAKE_INSTALL_RPATH='$ORIGIN' \
      || die "cmake configure failed. On a DGX Spark GB10 the architecture is $GB10_CUDA_ARCH and nothing else -- ./scripts/setup.sh --cuda --cuda-arch $GB10_CUDA_ARCH. Elsewhere, if 'native' is unsupported by this nvcc, name the architecture explicitly." 4
  fi

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
  info "$FLAVOR build finished in $((BUILD_SECONDS / 60))m $((BUILD_SECONDS % 60))s (commit ${SOURCE_COMMIT:-unknown})."
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
  if [ -z "$u" ]; then
    # The one case where a missing asset is not fatal: OpenVINO has a source
    # path that produces the SAME backend, so falling back changes the build
    # provenance and nothing a number depends on. Every other flavor here would
    # be falling back to a different backend, which is what section 4 refuses.
    if [ "$FLAVOR" = "openvino" ]; then
      warn "release $TAG publishes no ubuntu-openvino-$OV_VERSION-x64 asset -- building from source instead."
      return 1
    fi
    die "no asset in $TAG matches any of: $PAT_LIST -- release naming drifted; update the patterns at the top of this script." 4
  fi
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
    info "install : skip ($TAG / $FLAVOR already present); INSTALL.json rewritten with the recorded build provenance carried forward"
  elif [ "$WANT_OPENVINO" = 1 ]; then
    ov_paths
    if [ "$OV_SKIP_RUNTIME" = 1 ]; then
      info "runtime : skip (--skip-openvino-runtime); expects $OV_LIBDIR to exist"
    else
      info "runtime : OpenVINO $OV_VERSION -> $OV_ROOT, symlinked as $OV_PREFIX/openvino"
      info "          $OV_URL"
      info "          sha256 checked against the published sidecar and this script's pinned constant"
    fi
    if [ "$OV_FORCE_SOURCE" = 1 ]; then
      info "install : source build (--openvino-source) -> $DEST"
    else
      info "install : prebuilt asset if $TAG has one, else source build -> $DEST"
      info "          asset pattern: $PAT_OPENVINO_X64"
    fi
    info "          cmake fallback: -DGGML_OPENVINO=ON -DOpenVINO_DIR=$OV_ROOT/runtime/cmake"
    info "device  : GGML_OPENVINO_DEVICE=$OV_DEVICE (written into $DEST/openvino-env.sh)"
    info "note    : the backend requantises on every device and logs nothing; on NPU every"
    info "          quantized tensor but token_embd/output becomes Q4_0_128, so a quant"
    info "          ladder there is degenerate (rule 30). Recorded in INSTALL.json."
  elif [ "$WANT_CUDA" = 1 ]; then
    info "install : source build -> $DEST"
    info "          git clone --depth 1 --branch $TAG $UPSTREAM $SRC"
    info "          cmake -S $SRC -B $SRC/build -DGGML_CUDA=ON -DCMAKE_CUDA_ARCHITECTURES=$CUDA_ARCH -DCMAKE_BUILD_TYPE=Release"
    info "          cuda_arch source: $CUDA_ARCH_SOURCE$([ "$GB10" = 1 ] && echo "  (GB10: only 121a* is accepted)")"
    info "          targets: $TOOLS_REQUIRED $TOOLS_OPTIONAL"
  else
    info "install : binary release -> $DEST"
    info "          candidate assets, in order: $PAT_LIST"
  fi
  info "record  : $INSTALL_JSON  (tag, flavor=$FLAVOR, arch=$ARCH, os, assets, urls, installed_utc,"
  info "          built_from_source, cuda_arch + cuda_arch_source + cuda_arch_override, gb10,"
  info "          openvino_version/build/root/device/install_path/runtime_sha256, openvino_requantises,"
  info "          openvino_npu_quant_ladder_degenerate, multimodal_supported, cpu_gen, npu_status)"
  if [ "$DO_VENV" = 1 ]; then
    info "python  : $ROOT/.venv + $([ "$PUBLISH" = 1 ] && echo requirements.txt || echo requirements-min.txt)"
  else
    info "python  : skipped (--no-venv)"
  fi
  info "--- end of plan; nothing was changed ---"
  exit 0
fi

# The runtime is checked and installed OUTSIDE the idempotency skip. Skipping
# the llama.cpp install says the binaries are already here; it says nothing
# about the runtime they link against, and a missing runtime is what an
# "already installed" server fails on at its first launch.
[ "$WANT_OPENVINO" = 1 ] && install_openvino_runtime

if [ "$SKIP_INSTALL" -eq 0 ]; then
  if [ "$WANT_OPENVINO" = 1 ]; then
    if [ "$OV_FORCE_SOURCE" = 1 ]; then
      info "OpenVINO: source build (--openvino-source); the prebuilt asset is not consulted."
      OV_INSTALL_PATH="source-build"
      build_from_source
    elif download_release; then
      OV_INSTALL_PATH="prebuilt-asset"
      info "OpenVINO: took the prebuilt $TAG asset, built against OpenVINO $OV_VERSION."
    else
      OV_INSTALL_PATH="source-build"
      have cmake || die "the prebuilt OpenVINO asset is absent from $TAG and cmake is not here to build one: sudo apt-get install -y cmake build-essential git" 3
      have git   || die "the prebuilt OpenVINO asset is absent from $TAG and git is not here to clone one: sudo apt-get install -y git" 3
      build_from_source
    fi
  elif [ "$WANT_CUDA" = 1 ]; then
    build_from_source
  else
    download_release
  fi
fi

# ----------------------------------------------------------- 9. verify it runs
[ -x "$EXE" ] || die "llama-server not found at $EXE after the install." 4
NEEDS_LD_PATH=false; LD_PATH_VALUE=""
# The OpenVINO runtime deliberately stays in its swappable versioned prefix, so
# an OpenVINO build is the normal case for needing a loader path, not a defect.
[ "$FLAVOR" = "openvino" ] && ov_resolve_libdir
LD_CANDIDATE="$DEST"
[ -n "$OV_LIBDIR" ] && [ -d "$OV_LIBDIR" ] && LD_CANDIDATE="$DEST:$OV_LIBDIR"
if VER_OUT="$("$EXE" --version 2>&1)"; then
  :
elif VER_OUT="$(LD_LIBRARY_PATH="$LD_CANDIDATE" DYLD_LIBRARY_PATH="$LD_CANDIDATE" "$EXE" --version 2>&1)"; then
  NEEDS_LD_PATH=true; LD_PATH_VALUE="$LD_CANDIDATE"
  warn "llama-server only runs with LD_LIBRARY_PATH=$LD_CANDIDATE."
  warn "Export that before running any harness script, or the campaign dies at its first server launch."
else
  die "llama-server --version failed: $VER_OUT" 4
fi
# One file to source, so the loader path and the device do not have to be
# remembered separately at every launch, and so the device that ran is written
# down somewhere a later reader can find it (rule 28).
if [ "$FLAVOR" = "openvino" ]; then
  {
    printf '# written by scripts/setup.sh -- source before launching llama-server\n'
    printf '# OpenVINO %s (%s), device %s\n' "$OV_VERSION" "$OV_BUILD" "$OV_DEVICE"
    printf 'export LD_LIBRARY_PATH="%s${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"\n' "${LD_PATH_VALUE:-$LD_CANDIDATE}"
    printf 'export GGML_OPENVINO_DEVICE=%s\n' "$OV_DEVICE"
    printf '# GGML_OPENVINO_STATEFUL_EXECUTION=1 is experimental, faster on CPU/GPU, and\n'
    printf '# limits llama-server to ONE chat session -- do not set it under a sweep that\n'
    printf '# uses parallel slots, and record it as an arm condition if you do set it.\n'
    printf '# GGML_OPENVINO_DUMP_IR=1 dumps the graph that actually ran: the only way to\n'
    printf '# prove which tensor types executed, since the type-change log lines are\n'
    printf '# commented out at ggml-openvino.cpp:332-346.\n'
  } > "$DEST/openvino-env.sh"
  info "Wrote $DEST/openvino-env.sh (LD_LIBRARY_PATH + GGML_OPENVINO_DEVICE=$OV_DEVICE)."
fi
VER_OUT="$(printf '%s\n' "$VER_OUT" | head -n2 | tr '\n' ' ')"
printf '%s\n' "$TAG" > "$VFILE"

# ------------------------------------------- 10. INSTALL.json: what this IS
# FLAVOR used to be computed and thrown away, so no report could state whether
# its numbers were CUDA, Vulkan, Metal or CPU -- rule 3's strongest condition,
# unrecorded. Written here, the moment it is known (rule 28).
TOOLS_JSON=""
for t in ${TOOLS_BUILT:-}; do TOOLS_JSON="${TOOLS_JSON:+$TOOLS_JSON, }$(json_str "$t")"; done
NPU_JSON=""
for t in ${NPU_FINDINGS[@]+"${NPU_FINDINGS[@]}"}; do NPU_JSON="${NPU_JSON:+$NPU_JSON, }$(json_str "$t")"; done

# ---- what the INSTALL ACT established, carried forward across a skip ----------
# A re-run that installs nothing must not rewrite the record as though it had.
# Before this, running setup.sh twice after a CUDA source build left
# built_from_source:false, cuda_arch:null, source_commit:null and empty assets:
# the second, idempotent run erased the first run's provenance. That is rule 3's
# strongest condition deleted by a no-op, and nothing would have said so.
# Every value here is read BEFORE the writer block below, because the `>`
# redirection truncates the file before any command inside it runs.
prev_raw() {
  local v
  [ -f "$INSTALL_JSON" ] || return 0
  v="$(sed -n "s/^[[:space:]]*\"$1\"[[:space:]]*:[[:space:]]*\(.*\)\$/\1/p" "$INSTALL_JSON" | head -1)"
  v="${v%"${v##*[![:space:]]}"}"   # rtrim
  v="${v%,}"                       # the one trailing comma this writer emits
  v="${v%"${v##*[![:space:]]}"}"
  # Accept only a COMPLETE JSON value standing alone on its line. Both setup
  # scripts write one field per line, so anything else -- two fields on one
  # line, a wrapped array -- came from a hand-edited file, and taking the rest
  # of that line verbatim would emit a record no reader can open. Rejecting it
  # loses one carried field; accepting it loses the whole file. Fail towards
  # losing the field.
  case "$v" in
    null|true|false) printf '%s' "$v"; return 0 ;;
  esac
  printf '%s' "$v" | grep -qE '^-?[0-9]+([.][0-9]+)?$' && { printf '%s' "$v"; return 0; }
  printf '%s' "$v" | grep -qE '^"[^"]*"$'              && { printf '%s' "$v"; return 0; }
  printf '%s' "$v" | grep -qE '^\[[^][]*\]$'           && { printf '%s' "$v"; return 0; }
  return 0
}
J_BUILT="$BUILT"
J_SOURCE_COMMIT="$(json_or_null "$SOURCE_COMMIT")"
J_BUILD_SECONDS="${BUILD_SECONDS:-null}"
J_TOOLS="[$TOOLS_JSON]"
J_ASSETS="[$ASSETS_JSON]"
J_URLS="[$URLS_JSON]"
J_CUDA_ARCH=null; J_CUDA_ARCH_SOURCE=null; J_CUDA_ARCH_OVERRIDE=false
if [ "$BUILT" = true ] && [ "$FLAVOR" = "cuda" ]; then
  J_CUDA_ARCH="$(json_str "$CUDA_ARCH")"
  J_CUDA_ARCH_SOURCE="$(json_str "$CUDA_ARCH_SOURCE")"
  [ "$CUDA_ARCH_OVERRIDE" = 1 ] && J_CUDA_ARCH_OVERRIDE=true
fi
J_OV_VERSION=null; J_OV_BUILD=null; J_OV_ROOT=null; J_OV_DEVICE=null
J_OV_PATH=null; J_OV_RUNTIME=null; J_OV_SHA=null; J_OV_SHA_SRC=null
J_OV_REQUANT=null; J_OV_LADDER=null; J_MULTIMODAL=true
if [ "$FLAVOR" = "openvino" ]; then
  J_OV_VERSION="$(json_str "$OV_VERSION")"
  J_OV_BUILD="$(json_str "$OV_BUILD")"
  J_OV_ROOT="$(json_or_null "$OV_ROOT")"
  J_OV_DEVICE="$(json_str "$OV_DEVICE")"
  J_OV_PATH="$(json_or_null "$OV_INSTALL_PATH")"
  J_OV_RUNTIME="$(json_or_null "$OV_RUNTIME_SOURCE")"
  J_OV_SHA="$(json_or_null "$OV_SHA256")"
  J_OV_SHA_SRC="$(json_or_null "$OV_SHA_SOURCE")"
  # Not a warning flag: a fact about what ran, so a report can state it and a
  # planner can refuse a ladder without re-deriving it from the source tree.
  J_OV_REQUANT=true
  if [ "$OV_DEVICE" = "NPU" ]; then J_OV_LADDER=true; else J_OV_LADDER=false; fi
  J_MULTIMODAL=false   # ggml-openvino is text-only; multimodal is incomplete
fi
J_LD_PATH="$(json_or_null "$LD_PATH_VALUE")"
J_CPU_GEN=null; J_NPU_STATUS=null
[ "$CPU_GEN" != unknown ] && J_CPU_GEN="$(json_str "$CPU_GEN")"
[ "$NPU_STATUS" != not-checked ] && J_NPU_STATUS="$(json_str "$NPU_STATUS")"
# openvino_device, needs_ld_library_path and ld_library_path are deliberately
# NOT carried forward: the verify step and openvino-env.sh are rewritten on every
# run, including a skip, so those three are re-measured and must agree with the
# file that was just written rather than with the previous run's choice.
if [ "$SKIP_INSTALL" -eq 1 ]; then
  for k in built_from_source:J_BUILT source_commit:J_SOURCE_COMMIT \
           build_seconds:J_BUILD_SECONDS tools:J_TOOLS assets:J_ASSETS urls:J_URLS \
           cuda_arch:J_CUDA_ARCH cuda_arch_source:J_CUDA_ARCH_SOURCE \
           cuda_arch_override:J_CUDA_ARCH_OVERRIDE \
           openvino_version:J_OV_VERSION openvino_build:J_OV_BUILD \
           openvino_root:J_OV_ROOT \
           openvino_install_path:J_OV_PATH openvino_runtime_source:J_OV_RUNTIME \
           openvino_runtime_sha256:J_OV_SHA openvino_runtime_sha256_provenance:J_OV_SHA_SRC \
           openvino_requantises:J_OV_REQUANT \
           openvino_npu_quant_ladder_degenerate:J_OV_LADDER \
           multimodal_supported:J_MULTIMODAL; do
    PREV_VAL="$(prev_raw "${k%%:*}")"
    [ -n "$PREV_VAL" ] && printf -v "${k#*:}" '%s' "$PREV_VAL"
  done
  info "Install skipped: build provenance carried forward from the existing INSTALL.json."
fi
{
  printf '{\n'
  printf '  "tag": %s,\n'                    "$(json_str "$TAG")"
  printf '  "flavor": %s,\n'                 "$(json_str "$FLAVOR")"
  printf '  "arch": %s,\n'                   "$(json_str "$ARCH")"
  printf '  "os": %s,\n'                     "$(json_str "$OS_TOKEN")"
  printf '  "os_version": %s,\n'             "$(json_str "$OS_DESC")"
  printf '  "host": %s,\n'                   "$(json_str "$(uname -n 2>/dev/null || printf unknown)")"
  printf '  "assets": %s,\n'                 "$J_ASSETS"
  printf '  "urls": %s,\n'                   "$J_URLS"
  printf '  "installed_utc": %s,\n'          "$(json_str "$(date -u +%Y-%m-%dT%H:%M:%SZ)")"
  printf '  "built_from_source": %s,\n'      "$J_BUILT"
  printf '  "cuda_arch": %s,\n'              "$J_CUDA_ARCH"
  printf '  "cuda_arch_source": %s,\n'       "$J_CUDA_ARCH_SOURCE"
  printf '  "cuda_arch_override": %s,\n'     "$J_CUDA_ARCH_OVERRIDE"
  printf '  "gb10": %s,\n'                   "$([ "$GB10" = 1 ] && echo true || echo false)"
  printf '  "compute_cap": %s,\n'            "$(json_or_null "$COMPUTE_CAP")"
  printf '  "openvino_version": %s,\n'       "$J_OV_VERSION"
  printf '  "openvino_build": %s,\n'         "$J_OV_BUILD"
  printf '  "openvino_root": %s,\n'          "$J_OV_ROOT"
  printf '  "openvino_device": %s,\n'        "$J_OV_DEVICE"
  printf '  "openvino_install_path": %s,\n'  "$J_OV_PATH"
  printf '  "openvino_runtime_source": %s,\n' "$J_OV_RUNTIME"
  printf '  "openvino_runtime_sha256": %s,\n' "$J_OV_SHA"
  printf '  "openvino_runtime_sha256_provenance": %s,\n' "$J_OV_SHA_SRC"
  printf '  "openvino_requantises": %s,\n'   "$J_OV_REQUANT"
  printf '  "openvino_npu_quant_ladder_degenerate": %s,\n' "$J_OV_LADDER"
  printf '  "multimodal_supported": %s,\n'   "$J_MULTIMODAL"
  printf '  "cpu_gen": %s,\n'                "$J_CPU_GEN"
  printf '  "npu_status": %s,\n'             "$J_NPU_STATUS"
  printf '  "npu_findings": [%s],\n'         "$NPU_JSON"
  printf '  "gpu": %s,\n'                    "$(json_str "$GPU")"
  printf '  "gpu_name": %s,\n'               "$(json_or_null "$GPU_NAME")"
  printf '  "driver_version": %s,\n'         "$(json_or_null "$DRIVER")"
  printf '  "server_version": %s,\n'         "$(json_str "$VER_OUT")"
  printf '  "source_commit": %s,\n'          "$J_SOURCE_COMMIT"
  printf '  "build_seconds": %s,\n'          "$J_BUILD_SECONDS"
  printf '  "tools": %s,\n'                  "$J_TOOLS"
  printf '  "needs_ld_library_path": %s,\n'  "$NEEDS_LD_PATH"
  printf '  "ld_library_path": %s,\n'        "$J_LD_PATH"
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
if [ "$BUILT" = true ] && [ "$FLAVOR" = "cuda" ]; then
  echo "  Flavor   : $FLAVOR  (built from source, CMAKE_CUDA_ARCHITECTURES=$CUDA_ARCH [$CUDA_ARCH_SOURCE], commit ${SOURCE_COMMIT:-?}, ${BUILD_SECONDS}s)"
  echo "  Tools    : ${TOOLS_BUILT:-none}${TOOLS_MISSING:+   (not built: $TOOLS_MISSING)}"
elif [ "$BUILT" = true ]; then
  echo "  Flavor   : $FLAVOR  (built from source, commit ${SOURCE_COMMIT:-?}, ${BUILD_SECONDS}s)"
  echo "  Tools    : ${TOOLS_BUILT:-none}${TOOLS_MISSING:+   (not built: $TOOLS_MISSING)}"
else
  echo "  Flavor   : $FLAVOR  (official binary release)"
fi
if [ "$FLAVOR" = "openvino" ]; then
  echo "  OpenVINO : $OV_VERSION ($OV_BUILD) at ${OV_ROOT:-?}, device $OV_DEVICE, via ${OV_INSTALL_PATH:-?}"
  echo "  Env      : source $DEST/openvino-env.sh before any launch"
fi
[ "$GB10" = 1 ] && echo "  Board    : DGX Spark GB10 -- unified memory, no discrete board"
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
if [ "$FLAVOR" = "openvino" ]; then
  cat <<OVEND

  AND THE FILE ON DISK IS NOT THE WEIGHTS THAT RAN. OpenVINO requantises before
  it executes, on every device, and the log lines that would say so are
  commented out. token_embd and output are rewritten always; Q6_K and Q5_K
  become Q8_0_C off NPU -- more bits at a COARSER scale granularity, one scale
  per row, so do not write it up as an upgrade. INSTALL.json now carries
  openvino_requantises: true. Two consequences you cannot design around:
    - A quant file name is not a description of the arm. State the requantisation
      beside every OpenVINO number (rule 3), and prove what ran with
      GGML_OPENVINO_DUMP_IR=1 rather than from the filename.
    - On NPU a quant ladder compares identical weights. Run ladders on CPU or GPU.
  Multimodal is incomplete in this backend: INSTALL.json records
  multimodal_supported: false, so a vision stage here measures nothing (rule 2).
  Capture 'OpenVINO: using device' from the server log on the first launch -- it
  prints the RESOLVED device after availability fallback, so it is the one line
  that catches a silent NPU-to-CPU downgrade.
OVEND
fi
if [ "$GB10" = 1 ]; then
  cat <<GBEND

  GB10 has 128 GB of UNIFIED memory and no discrete board, so nvidia-smi VRAM
  sampling and the board_total_mib - reserve fit arithmetic both fail SILENTLY
  here. Do not derive a fit ceiling (rule 13) from either; see
  reference/platform-notes.md, 'DGX Spark reports VRAM that is not a board'.
GBEND
fi
if [ "$FLAVOR" = "openvino" ]; then
  cat <<'DETECTEND'

  scripts/detect-machine.py reads 'openvino' out of INSTALL.json as the MEASURED
  backend, so machine.json and this record agree without a --backend flag. Check
  that they do agree before either reaches a report.
DETECTEND
fi
