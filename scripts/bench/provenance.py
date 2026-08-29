# -*- coding: utf-8 -*-
"""What was this measurement taken WITH? Recorded once, by every probe.

WHY THIS EXISTS, and it is a defect this campaign published rather than a
precaution. On 2026-08-28 one configuration - UD-IQ4_XS, n-max 10 / p-min 0.5,
-c 32768, -ngl 99, --parallel 1, -fa on, KV q8_0, greedy, 700 predicted tokens,
the same prompt - was found to read 80.0 t/s where the archive held 86.91,
87.4, 93.9 and 106.2 for the identical flags. Probe pacing explained 6.9 points
of a 25-point gap. Every other candidate was ruled out because the conditions
matched. The one remaining candidate was the llama.cpp build, AND IT COULD NOT
BE CHECKED: the 2026-08-21 server logs on disk are zero bytes, and only three
artefacts in the entire repository recorded a build string at all.

A throughput number whose toolchain is not recorded cannot be compared with a
later one. It is not reproducible, and this campaign had been publishing those.

Rule 3 says the conditions travel with the number. The server binary IS a
condition - arguably the strongest one, because it changes what the same flags
do - and it was the one condition nothing captured.

WHAT IS CAPTURED, and why each:

  llama.cpp build and commit   the binary that did the decoding
  binary size and mtime        catches a rebuilt binary that kept its version
                               string, which a version string alone cannot
  NVIDIA driver version        owns the clock and power behaviour under the cap
  GPU name and board limit     the card, and whether its cap is at stock
  model file size and mtime    catches a re-quantised file under the same name
  python version and platform  the harness itself
  the EXECUTION CONTEXT        the backend, the RESOLVED device, the CUDA
                               architecture the kernels were compiled for, the
                               OpenVINO runtime version and its stateful flag,
                               and the install tag - see below

ABSENCE IS RECORDED, NEVER OMITTED. Every field that cannot be read is written
as an explicit "NOT RECORDED: <reason>" string rather than dropped, because a
missing key reads as "not applicable" to whoever finds the artefact later, and
that is exactly how the 2026-08-21 numbers came to look comparable when they
were not.

THE EXECUTION CONTEXT, AND WHY IT IS A CONDITION RATHER THAN A NOTE. Until this
block existed, no artefact in this repository said which BACKEND produced its
numbers. On one machine with one build that was survivable. It stops being
survivable the moment a second backend is in play, and llama.cpp ships several
that will decode the same GGUF on the same box:

  cuda       what every number in results/qwen38-27b-blind/ was measured on
  openvino   ggml/src/ggml-openvino/, in mainline since 2026-03-14
  vulkan     what scripts/setup.sh installs on Linux unless --cuda is given
  sycl / rocm / metal / cpu

and the OpenVINO one does not run the weights that are in the file. Before the
first token it rewrites them (ggml/src/ggml-openvino/ggml-openvino-extra.cpp
lines 252-273, through requantize_to_buffers at ggml-quants.cpp:841, which
dequantises to F32 and re-quantises):

  token_embd.weight -> F16 on NPU from a Q6_K source, otherwise Q8_0_C
  output.weight     -> Q8_0_C, always, on every device
  on NPU            -> Q4_0_128 for EVERY other quantized tensor, whatever the
                       file said; even a Q4_0 file is re-blocked from 32
                       weights per scale to 128
  elsewhere         -> Q6_K and Q5_K both become Q8_0_C

Q8_0_C and Q4_0_C are CHANNEL-WISE: one scale per row (weights_per_block =
tensor->ne[0]). Q6_K -> Q8_0_C is more bits at coarser scale granularity, which
is a rewrite, not an upgrade.

AND THE REWRITE IS SILENT. The four GGML_LOG_DEBUG lines that would report a
tensor changing type are commented out at ggml-openvino.cpp:332-346, and
/props carries only ov::get_openvino_version().description
(ggml-openvino.cpp:1546) - the version string, nothing about quantisation. One
line survives, and this module goes and gets it:

    GGML_LOG_INFO("OpenVINO: using device %s\\n", ...)   ggml-openvino.cpp:1526

emitted once from ggml_openvino_init() with the device it RESOLVED, after the
availability fallback. GGML_OPENVINO_DEVICE says what was asked for; that line
says what was given, and a silent NPU -> CPU downgrade is exactly the
difference between them. So the log path is an argument to toolchain(), and a
probe that does not pass one gets "NOT RECORDED" with the reason, never a
guess. GGML_OPENVINO_DUMP_IR=1 proves what actually ran when the log is gone.
"""
import os
import platform
import re
import subprocess
import sys


def _run(args, timeout=20):
    try:
        p = subprocess.run(args, capture_output=True, text=True,
                           timeout=timeout)
        return ((p.stdout or "") + (p.stderr or "")).strip()
    except Exception as exc:
        return "NOT RECORDED: %s: %s" % (type(exc).__name__, exc)


def _stat(path):
    """Size and mtime of a file, so a rebuild that kept its version string is
    still visible."""
    try:
        st = os.stat(path)
        return {"path": path, "bytes": st.st_size,
                "mtime": __import__("time").strftime(
                    "%Y-%m-%d %H:%M:%S", __import__("time").localtime(st.st_mtime))}
    except Exception as exc:
        return {"path": path,
                "bytes": "NOT RECORDED: %s" % type(exc).__name__,
                "mtime": "NOT RECORDED: %s" % type(exc).__name__}


def server_build(server_path):
    """llama.cpp build and commit, read from the binary that will run.

    Parsed from `llama-server --version`, which prints e.g.
        version: 0.1.2-dev (build 10502, commit 0adcc3bb5)
    The raw line is kept alongside the parsed fields, so a format change
    degrades to 'the raw string is still here' rather than to silence.
    """
    raw = _run([server_path, "--version"])
    out = {"raw": raw, "binary": _stat(server_path)}
    # The launcher is a stub - 9,216 bytes on this rig - so its own mtime says
    # nothing about the code that decodes. Stat the compute libraries beside
    # it, which are where a rebuild actually lands. This is what ruled the
    # build out as the cause of the 2026-08-28 throughput gap: every ggml
    # library was dated 2026-08-19, unchanged across every measurement in
    # question.
    try:
        d = os.path.dirname(os.path.abspath(server_path))
        libs = sorted(f for f in os.listdir(d)
                      if f.lower().startswith("ggml")
                      and f.lower().endswith((".dll", ".so")))
        out["compute_libraries"] = [_stat(os.path.join(d, f)) for f in libs]
        if not libs:
            out["compute_libraries"] = ("NOT RECORDED: no ggml libraries "
                                        "found beside the server binary")
    except Exception as exc:
        out["compute_libraries"] = ("NOT RECORDED: %s: %s"
                                    % (type(exc).__name__, exc))
    m = re.search(r"build\s+(\d+)", raw)
    out["build"] = m.group(1) if m else "NOT RECORDED: no build number in --version output"
    m = re.search(r"commit\s+([0-9a-f]+)", raw)
    out["commit"] = m.group(1) if m else "NOT RECORDED: no commit in --version output"
    m = re.search(r"version:\s*(\S+)", raw)
    out["version"] = m.group(1) if m else "NOT RECORDED: no version in --version output"
    return out


def gpu_state():
    """Driver, card, and whether the board limit is at its stock value.

    The cap is persistent hardware state that survives the process, so an
    artefact that does not record it cannot prove it was measured at stock.
    """
    q = ("driver_version,name,power.limit,power.default_limit,"
         "memory.total,clocks.max.sm")
    raw = _run(["nvidia-smi", "--query-gpu=" + q,
                "--format=csv,noheader,nounits"])
    if raw.startswith("NOT RECORDED"):
        return {"raw": raw}
    parts = [x.strip() for x in raw.split(",")]
    if len(parts) < 6:
        return {"raw": raw,
                "note": "NOT RECORDED: unexpected nvidia-smi field count"}
    out = {"raw": raw, "driver": parts[0], "name": parts[1],
           "power_limit_w": parts[2], "power_default_limit_w": parts[3],
           "memory_total_mib": parts[4], "max_sm_mhz": parts[5]}
    try:
        out["cap_at_stock"] = abs(float(parts[2]) - float(parts[3])) < 1.0
    except ValueError:
        out["cap_at_stock"] = "NOT RECORDED: power limits unparseable"
    return out


# ---------------------------------------------------------------------------
# THE EXECUTION CONTEXT
#
# Every field below carries HOW it was obtained, in the four categories
# scripts/detect-machine.py uses - MEASURED, DERIVED, CITED, UNKNOWN - because
# "openvino" read out of a server log and "openvino" assumed from an
# environment variable are not the same claim, and a reader who cannot tell
# them apart cannot falsify either.
# ---------------------------------------------------------------------------

BACKENDS = ("cuda", "openvino", "vulkan", "sycl", "rocm", "metal", "cpu")

# ggml/src/ggml-openvino/ggml-openvino.cpp:1526, in ggml_openvino_init(). The
# ONE line that names the device the backend resolved, printed after the
# availability fallback - so it catches the NPU -> CPU downgrade that
# GGML_OPENVINO_DEVICE cannot.
OV_DEVICE_RE = re.compile(r"OpenVINO:\s*using device\s+([^\s,;]+)")

# libopenvino.so.2026.3.1 -> 2026.3.1. The runtime tarball this repo pins is
# 2026.3.1 (full string 2026.3.1.22476.56d9685302d), and the soname is the only
# place that version appears on disk without running anything.
OV_SONAME_RE = re.compile(r"^libopenvino\.so\.(\d+\.\d+[\w.]*)$")

# The environment the OpenVINO backend reads. Recorded as ASKED FOR, never as
# what happened: the resolved device comes from the log line, and those two
# disagreeing is the finding, not an inconsistency to smooth over.
OV_ENV_VARS = ("GGML_OPENVINO_DEVICE", "GGML_OPENVINO_STATEFUL_EXECUTION",
               "GGML_OPENVINO_DUMP_IR", "GGML_OPENVINO_CACHE_DIR")

REQUANTISATION = (
    "OpenVINO rewrites the file's weights before it runs them, so the GGUF on "
    "disk is not what decoded: token_embd.weight and output.weight always "
    "become Q8_0_C, Q6_K and Q5_K become Q8_0_C, and on NPU every other "
    "quantized tensor becomes Q4_0_128 whatever the file said (even Q4_0 is "
    "re-blocked from 32 weights per scale to 128). "
    "ggml/src/ggml-openvino/ggml-openvino-extra.cpp:252-273; the rewrite is "
    "requantize_to_buffers at ggml-quants.cpp:841, which dequantises to F32 "
    "and re-quantises. It is not logged: the debug lines that would report a "
    "tensor changing type are commented out at ggml-openvino.cpp:332-346.")

NPU_COLLAPSE = (
    "On NPU every quantized tensor except the embeddings and the output "
    "projection becomes Q4_0_128, whatever the file was, so a quant ladder "
    "here is one arm repeated: Q8_0, Q6_K, Q5_K, Q4_K_M, Q4_1 and Q4_0 all "
    "decode as the same weights (ggml-openvino-extra.cpp:252-273).")


def _repo_root():
    """The repo root, derived from this file - never from the cwd."""
    here = os.path.dirname(os.path.abspath(__file__))          # scripts/bench
    return os.path.dirname(os.path.dirname(here))


def _os_token():
    return {"win32": "windows", "darwin": "macos"}.get(sys.platform, "linux")


def _reason(text):
    """A reason, said once. Absences compose, and "NOT RECORDED: NOT RECORDED:"
    is how a reader learns to stop reading them."""
    text = str(text or "no reason recorded")
    if text.startswith("NOT RECORDED: "):
        return text[len("NOT RECORDED: "):]
    return text


def install_record(server_path=None, repo_root=None):
    """bin/llama.cpp/INSTALL.json - what the setup script recorded it built.

    The backend flavor and CMAKE_CUDA_ARCHITECTURES already live there
    (scripts/setup.sh section 10, scripts/setup.ps1), so nothing here
    re-derives them; this reads them and says whether they describe the binary
    that is about to run. Often they do not: results/qwen38-27b-blind/ was
    measured with E:\\AI\\llama.cpp\\llama-server.exe while bin/llama.cpp/ held
    a WSL2 Linux build, and an INSTALL.json pinned onto the wrong binary's
    numbers is worse than no INSTALL.json at all.
    """
    path = os.path.join(repo_root or _repo_root(), "bin", "llama.cpp",
                        "INSTALL.json")
    out = {"path": path}
    try:
        import json
        with open(path, "r", encoding="utf-8-sig") as fh:
            meta = json.load(fh) or {}
    except Exception as exc:
        out["read"] = "NOT RECORDED: %s: %s" % (type(exc).__name__, exc)
        out["describes_this_server"] = False
        out["why_not_this_server"] = out["read"]
        return out
    for k in ("tag", "flavor", "arch", "os", "host", "cuda_arch",
              "built_from_source", "source_commit", "server_version",
              "installed_utc", "vulkan_override"):
        out[k] = meta.get(k, "NOT RECORDED: absent from INSTALL.json")
    running = _os_token()
    if str(meta.get("os") or "").lower() not in ("", running):
        out["runs_here"] = False
        out["why"] = ("INSTALL.json describes a %s build and this box is %s, "
                      "so it says nothing about what decoded here"
                      % (meta.get("os"), running))
    else:
        out["runs_here"] = True
    if server_path:
        a = os.path.normcase(os.path.abspath(os.path.dirname(server_path)))
        b = os.path.normcase(os.path.abspath(os.path.dirname(path)))
        out["describes_this_server"] = (a == b) and out["runs_here"]
        if a != b:
            out["why_not_this_server"] = (
                "the server that ran is %s, and INSTALL.json describes the "
                "install in %s - a different toolchain, so its flavor and "
                "cuda_arch are NOT this measurement's" % (server_path, b))
        elif not out["runs_here"]:
            out["why_not_this_server"] = out["why"]
    else:
        out["describes_this_server"] = False
        out["why_not_this_server"] = ("NOT RECORDED: the probe passed no "
                                      "server path, so nothing ties "
                                      "INSTALL.json to the binary that ran")
        if not out["runs_here"]:
            out["why_not_this_server"] += "; and " + out["why"]
    return out


def openvino_device(server_log=None, log_text=None):
    """The device the OpenVINO backend RESOLVED, out of the server's own log.

    Reads ggml-openvino.cpp:1526's one line. Absence is never read as CPU: a
    log with no such line is a log that does not say, and this returns the
    reason instead of a device.
    """
    out = {"log": server_log or "NOT RECORDED: probe passed no server log",
           "source": "GGML_LOG_INFO(\"OpenVINO: using device %s\") - "
                     "ggml/src/ggml-openvino/ggml-openvino.cpp:1526, emitted "
                     "in ggml_openvino_init() AFTER the availability fallback"}
    if log_text is None:
        if not server_log:
            out["device"] = ("NOT RECORDED: no server log was passed, and the "
                             "resolved device is only ever printed there")
            return out
        try:
            with open(server_log, "r", encoding="utf-8",
                      errors="replace") as fh:
                log_text = fh.read()
        except Exception as exc:
            out["device"] = ("NOT RECORDED: could not read the server log: "
                             "%s: %s" % (type(exc).__name__, exc))
            return out
    hits = OV_DEVICE_RE.findall(log_text)
    if not hits:
        out["device"] = ("NOT RECORDED: the server log carries no \"OpenVINO: "
                         "using device\" line. Either this build is not the "
                         "OpenVINO backend, or the log was truncated. It is "
                         "not evidence of CPU.")
        return out
    out["device"] = hits[-1]
    out["occurrences"] = len(hits)
    if len(set(hits)) > 1:
        out["note"] = ("the log names more than one device (%s); the LAST is "
                       "recorded, and a probe that spans two servers has to "
                       "be split" % ", ".join(sorted(set(hits))))
    return out


def openvino_env(env=None):
    """What was ASKED for. What was given is openvino_device()."""
    env = os.environ if env is None else env
    return dict((name, env.get(name, "NOT SET")) for name in OV_ENV_VARS)


def openvino_runtime(server_path=None, env=None, props_description=None):
    """The OpenVINO runtime version, without running anything.

    Three sources, best first: the description llama-server already publishes
    at /props (ov::get_openvino_version().description, ggml-openvino.cpp:1546
    - hand it in, scripts/bench/bench.py reads /props anyway), then the soname
    of libopenvino.so beside the server or on the library path, then nothing,
    said out loud.
    """
    out = {}
    if props_description:
        m = re.search(r"(\d{4}\.\d+\.\d+[\w.]*)", str(props_description))
        out["version"] = m.group(1) if m else str(props_description)[:120]
        out["how"] = ("MEASURED: ov::get_openvino_version().description, read "
                      "from the running server's /props "
                      "(ggml-openvino.cpp:1546)")
        return out
    env = os.environ if env is None else env
    seen, roots = set(), []
    if server_path:
        roots.append(os.path.dirname(os.path.abspath(server_path)))
    for var in ("LD_LIBRARY_PATH", "INTEL_OPENVINO_DIR", "OpenVINO_DIR"):
        for part in (env.get(var) or "").split(os.pathsep):
            if part:
                roots += [part,
                          os.path.join(part, "runtime", "lib", "intel64")]
    for root in roots:
        if not root or root in seen:
            continue
        seen.add(root)
        try:
            names = sorted(os.listdir(root))
        except OSError:
            continue
        for name in names:
            m = OV_SONAME_RE.match(name)
            if m:
                out["version"] = m.group(1)
                out["how"] = "MEASURED: soname of %s" % os.path.join(root,
                                                                     name)
                return out
    out["version"] = ("NOT RECORDED: no libopenvino.so.<version> beside the "
                      "server binary or on LD_LIBRARY_PATH / "
                      "INTEL_OPENVINO_DIR, and no /props description was "
                      "passed")
    out["how"] = "UNKNOWN"
    out["searched"] = sorted(seen)
    return out


def _backend_from_install(install):
    """(flavor, how) out of INSTALL.json, or (None, why not)."""
    flavor = str(install.get("flavor") or "").lower()
    if flavor not in BACKENDS:
        return None, None
    if not install.get("describes_this_server"):
        return None, ("UNKNOWN: bin/llama.cpp/INSTALL.json records flavor "
                      "%r, but %s" % (flavor,
                                      install.get("why_not_this_server")))
    return flavor, ("MEASURED: bin/llama.cpp/INSTALL.json, written by the "
                    "setup script that installed the binary this probe ran")


def execution(server_path=None, server_log=None, env=None, backend=None,
              gpu=None, install=None, props_description=None):
    """The execution context: what decoded, on which device, compiled how.

    Order of evidence for the backend, strongest first, each one labelled on
    the field it produces:

      1. the server's own log said so     MEASURED  (the OpenVINO device line
                                                    is printed only when that
                                                    backend ran)
      2. the caller stated it             CITED
      3. INSTALL.json, for THIS binary    MEASURED
      4. nothing                          UNKNOWN, with the reason

    There is deliberately no fifth step. Deriving "cuda" from the presence of
    an NVIDIA card is wrong on exactly the machine this repository is being
    ported to: scripts/setup.sh installs the VULKAN build on Linux unless
    --cuda is passed, and there are no official Linux CUDA binaries.
    """
    env = os.environ if env is None else env
    install = install_record(server_path) if install is None else install
    ov_env = openvino_env(env)
    dev = openvino_device(server_log)
    resolved = dev.get("device")
    saw_ov_line = bool(resolved) and not str(resolved).startswith("NOT ")

    out = {"how": {}, "warnings": []}

    def put(key, value, how):
        out[key] = value
        out["how"][key] = how

    # ---- the backend
    if saw_ov_line:
        put("backend", "openvino",
            "MEASURED: the server log carries ggml-openvino.cpp:1526's "
            "\"OpenVINO: using device\" line, which only that backend prints")
        if backend and backend != "openvino":
            out["warnings"].append(
                "the caller said backend=%r and the server log says openvino; "
                "the log wins, because it is what ran" % backend)
    elif backend:
        put("backend", backend,
            "CITED: stated by the probe that called provenance.toolchain()")
    else:
        flavor, how = _backend_from_install(install)
        if flavor:
            put("backend", flavor, how)
        else:
            put("backend",
                "NOT RECORDED: no backend evidence. Pass backend= (what the "
                "probe launched), or server_log= for an OpenVINO run, or "
                "install bin/llama.cpp through scripts/setup.sh so that "
                "INSTALL.json describes the binary that runs.",
                how or "UNKNOWN")

    be = out["backend"] if out["backend"] in BACKENDS else None

    # ---- the resolved device
    asked = ov_env.get("GGML_OPENVINO_DEVICE")
    put("device_asked",
        asked if asked != "NOT SET"
        else "NOT SET (OpenVINO then defaults to CPU; every other backend "
             "ignores this variable)",
        "MEASURED: GGML_OPENVINO_DEVICE in this process's environment")
    if be == "openvino":
        if saw_ov_line:
            put("device", resolved, "MEASURED: %s" % dev["source"])
            if asked not in ("NOT SET", None) and asked != resolved:
                out["warnings"].append(
                    "SILENT FALLBACK: GGML_OPENVINO_DEVICE asked for %s and "
                    "the backend resolved %s. Every number from this run is a "
                    "%s number." % (asked, resolved, resolved))
        else:
            put("device", resolved,
                "UNKNOWN: %s" % ("no server log was passed"
                                 if not server_log
                                 else "the log does not carry the line"))
    elif be in ("cuda", "rocm", "vulkan", "sycl", "metal"):
        name = (gpu or {}).get("name")
        if name:
            put("device", name,
                "DERIVED: the %s build decodes on the card the GPU query "
                "named" % be)
        else:
            put("device",
                "NOT RECORDED: no GPU query answered, so the device this %s "
                "build used is unnamed" % be, "UNKNOWN")
    elif be == "cpu":
        put("device", "CPU", "DERIVED: the CPU build has one device")
    else:
        put("device",
            "NOT RECORDED: the backend itself is unknown, so its device "
            "cannot be named", "UNKNOWN")

    # ---- how the kernels were compiled
    arch = install.get("cuda_arch")
    if be == "cuda" and install.get("describes_this_server") \
            and arch and not str(arch).startswith("NOT RECORDED"):
        put("cuda_arch", arch,
            "MEASURED: CMAKE_CUDA_ARCHITECTURES from "
            "bin/llama.cpp/INSTALL.json, for this binary. It decides which "
            "kernels exist: DGX Spark GB10 needs 121a-real - not 120, 120f or "
            "native - to keep MMVQ_PARAMETERS_GB10")
    elif be == "cuda":
        put("cuda_arch",
            "NOT RECORDED: %s" % _reason(install.get("why_not_this_server")
                                         or install.get("why")
                                         or install.get("read")
                                         or "INSTALL.json records no "
                                            "cuda_arch"),
            "UNKNOWN")
    else:
        put("cuda_arch", None,
            "not applicable: the backend is %s" % (be or "unknown"))

    tag = install.get("tag")
    if tag and not str(tag).startswith("NOT RECORDED") \
            and install.get("describes_this_server"):
        put("build_tag", tag, "MEASURED: bin/llama.cpp/INSTALL.json tag")
    else:
        put("build_tag",
            "NOT RECORDED: %s" % _reason(install.get("why_not_this_server")
                                         or install.get("read")
                                         or "INSTALL.json describes another "
                                            "install"),
            "UNKNOWN")

    # ---- OpenVINO specifics
    if be == "openvino":
        rt = openvino_runtime(server_path, env, props_description)
        put("openvino_version", rt.get("version"), rt.get("how"))
        stateful = ov_env.get("GGML_OPENVINO_STATEFUL_EXECUTION")
        put("stateful_execution", stateful,
            "MEASURED: GGML_OPENVINO_STATEFUL_EXECUTION in this process's "
            "environment")
        if stateful not in ("NOT SET", "0", None):
            out["warnings"].append(
                "GGML_OPENVINO_STATEFUL_EXECUTION=%s: experimental, faster on "
                "CPU and GPU, and it limits llama-server to ONE chat session. "
                "A parallel-sequence probe under it is not measuring what its "
                "flags say." % stateful)
        put("requantisation", REQUANTISATION,
            "CITED: ggml-openvino-extra.cpp:252-273 and ggml-quants.cpp:841, "
            "read from the merged source")
        if str(out.get("device") or "").upper().startswith("NPU"):
            put("npu_quant_collapse", "Q4_0_128", "CITED: %s" % NPU_COLLAPSE)
            out["warnings"].append(NPU_COLLAPSE)
            if ov_env.get("GGML_OPENVINO_DUMP_IR") == "NOT SET":
                out["warnings"].append(
                    "GGML_OPENVINO_DUMP_IR is not set, so nothing in this run "
                    "proves which weights executed; the rewrite is not logged "
                    "(ggml-openvino.cpp:332-346).")
        out["openvino_env"] = ov_env
    else:
        put("openvino_version", None,
            "not applicable: the backend is %s" % (be or "unknown"))
        put("stateful_execution", None,
            "not applicable: the backend is %s" % (be or "unknown"))

    out["install_json"] = install
    out["resolved_device_probe"] = dev
    return out


def toolchain(server_path=None, model_path=None, server_log=None, env=None,
              backend=None, props_description=None):
    """The whole provenance block. Call once per probe and put it in the
    artefact, at the top level, beside the conditions.

    server_log is the path the probe told llama-server to write its stdout to
    - scripts/arms.py already keeps one per arm at work/<arm>-rep<N>.log and
    records it on every ledger line. Pass it: on OpenVINO that file is the
    only place the RESOLVED device appears, and scripts/ledger.py refuses to
    compare rows whose device differs.
    """
    gpu = gpu_state()
    block = {
        "recorded_by": "scripts/bench/provenance.py",
        "why": "rule 3 - the conditions travel with the number, and the "
               "server binary is a condition. A throughput figure whose "
               "build is unrecorded cannot be compared with a later one.",
        "python": sys.version.split()[0],
        "platform": platform.platform(),
        "gpu": gpu,
    }
    block["llama_cpp"] = (server_build(server_path) if server_path
                          else "NOT RECORDED: probe passed no server path")
    block["model_file"] = (_stat(model_path) if model_path
                           else "NOT RECORDED: probe passed no model path")
    block["execution"] = execution(server_path=server_path,
                                   server_log=server_log, env=env,
                                   backend=backend, gpu=gpu,
                                   props_description=props_description)
    return block


USAGE = """print this machine's toolchain block, the way a probe records it

    python provenance.py [llama-server] [model.gguf] [server.log] [backend]

Every argument is optional: the server is resolved through scripts/lib/paths
($LLAMA_SERVER, $LLAMA_DIR, PATH, <repo>/bin/llama.cpp) when it is omitted.
Pass the server log on an OpenVINO run - the RESOLVED device is printed there
and nowhere else, and a probe without it records "NOT RECORDED", never CPU."""

if __name__ == "__main__":
    import json
    # --help must answer without resolving anything: a help request that needs
    # a toolchain installed is a help request nobody can read on a fresh clone.
    if "--help" in sys.argv[1:] or "-h" in sys.argv[1:]:
        print(USAGE)
        sys.exit(0)
    sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__))), "lib"))
    import paths
    sp = paths.llama_bin("llama-server",
                         sys.argv[1] if len(sys.argv) > 1 else None)
    mp = sys.argv[2] if len(sys.argv) > 2 else None
    lg = sys.argv[3] if len(sys.argv) > 3 else None
    be = sys.argv[4] if len(sys.argv) > 4 else None
    print(json.dumps(toolchain(sp, mp, server_log=lg, backend=be), indent=2))
