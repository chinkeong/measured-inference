#!/usr/bin/env python3
"""Fixture campaigns for scripts/plan-campaign.py, built from REAL GGUF headers.

    python scripts/fixtures/plan-campaign-fixtures.py --write
    python scripts/fixtures/plan-campaign-fixtures.py --clean

WHY THIS FILE EXISTS. `plan-campaign.py` claims to be scale-free: give it any
model on any card and it derives the ladder instead of reciting the 22
hardcoded rungs of one 27B on one 24 GB card. A claim like that is only worth
what its counter-examples are worth, so this writes five campaigns that differ
on both axes -- model size, window size, capabilities, and the card itself --
and the plan for each is the evidence.

EVERY NUMBER BELOW IS MEASURED, not invented. `file_bytes`, `params_total`,
`arch`, `context_length`, `block_count`, `head_count`, `head_count_kv`,
`head_dim` and the projector/drafter sizes were read on 2026-08-29 out of the
real files on huggingface.co, through `scripts/quant-ladder/gguf-inspect.py`'s
remote mode -- a few MB of ranged GETs per file, nothing downloaded. The one
thing a header does NOT state is which layers are full attention, and for the
three hybrids here it does, in a per-layer `head_count_kv` array: LFM2 carries 8
kv-heads on 6 of its 16 blocks and 0 on the rest, granitehybrid on 4 of 40. The
`full_attn` field below is the count of non-zero entries in that array, and
`kv_bytes_per_token` is computed from it here rather than pasted, so the
arithmetic is visible.

The reference 3090's `machine.json` numbers are the ones written down in
`scripts/lib/paths.py`'s own schema block: 24,576 MiB board, desktop reserve
max 1,796 MiB over n=9 samples. The 12 GB variant exists to move the CARD while
holding the model still.

These are fixtures and they say so: each `model-*.json` carries `"_fixture":
true` and each directory a FIXTURE.md. `--clean` removes exactly what `--write`
created and nothing else -- which matters, because several `machine.json` files
under `results/` make `paths.py` refuse to guess which campaign a command meant.
Any slug that already has a `campaign.md` is a real campaign and is refused.
"""
import argparse
import io
import json
import os
import shutil
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
RESULTS = os.path.join(ROOT, "results")

# element bytes per KV value, matching scripts/check-request.py's CACHE_TYPES
ELEM = {"f16": 2.0, "q8_0": 34.0 / 32.0, "q4_0": 18.0 / 32.0}

REF_3090 = {"board_total_mib": 24576,
            "desktop_reserve_mib": {"min": 412, "max": 1796, "n": 9,
                                    "date": "2026-08-27"},
            "provenance": {"board_total_mib": {"how": "nvidia-smi "
                                               "--query-gpu=memory.total"},
                           "desktop_reserve_mib": {"how": "n=9 samples of board "
                                                   "VRAM with no server loaded, "
                                                   "over a working desktop"}}}

CARD_12GB = {"board_total_mib": 12288,
             "desktop_reserve_mib": {"min": 412, "max": 1796, "n": 9,
                                     "date": "2026-08-27"},
             "provenance": {"board_total_mib": {"how": "FIXTURE: the reference "
                                                "3090's measured desktop reserve "
                                                "held against a 12 GB board, to "
                                                "move the CARD while holding the "
                                                "model still"}}}

INSPECTED = "2026-08-29T00:00:00Z"
BUILD_TAG = "d7bd3bf-cuda"          # bin/llama.cpp/INSTALL.json's tag + flavor


def model(repo, fname, file_bytes, params, arch, ctx, blocks, heads, kv_heads,
          head_dim, embed, full_attn, caps, vision=None, drafter=None,
          effort=False, template_sha=None, note=None):
    """One model-<label>.json record, with kv_bytes_per_token computed here."""
    formula = ("2 x %d full-attention layers x %d kv-heads x %d head-dim x "
               "bytes-per-element (stage-1.md). %d of the %d blocks carry "
               "K/V; the rest are %s and hold a fixed-size state instead."
               % (full_attn, kv_heads, head_dim, full_attn, blocks,
                  "linear/gated" if full_attn < blocks else "n/a")
               if full_attn < blocks else
               "2 x %d layers x %d kv-heads x %d head-dim x bytes-per-element "
               "(stage-1.md; every layer is full attention)"
               % (blocks, kv_heads, head_dim))
    kv = {}
    for name, eb in ELEM.items():
        kv[name] = int(round(2 * full_attn * kv_heads * head_dim * eb))
    kv["formula"] = formula
    rec = {
        "_fixture": True,
        "_fixture_note": (note or "header read remotely from huggingface.co on "
                          "2026-08-29 via scripts/quant-ladder/gguf-inspect.py"),
        "repo": repo, "file": fname, "file_bytes": file_bytes,
        "sha256_head": None, "inspected_utc": INSPECTED, "build_tag": BUILD_TAG,
        "arch": arch, "arch_supported": True,
        "params_total": params,
        "bpw": round(file_bytes * 8.0 / params, 4),
        "context_length": ctx,
        "block_count": blocks, "head_count": heads, "head_count_kv": kv_heads,
        "head_dim": head_dim, "embedding_length": embed,
        "kv_bytes_per_token": kv,
        "vision": vision, "drafter": drafter,
        "chat_template": {"present": True, "sha256": template_sha,
                          "effort_knob": effort, "jinja_ok": True,
                          "why": None if effort else
                          "no reasoning_effort / thinking variable in the "
                          "template"},
        "capabilities": caps,
        "provenance": {
            "arch": "MEASURED general.architecture",
            "params_total": "MEASURED by summing the tensor table",
            "bpw": "DERIVED file_bytes*8/params_total",
            "context_length": "MEASURED %s.context_length" % arch,
            "head_count_kv": ("MEASURED %s.attention.head_count_kv" % arch),
            "kv_bytes_per_token": {"formula": formula, "how": "DERIVED"},
            "arch_supported": "FIXTURE: asserted true against build " + BUILD_TAG,
            "sha256_head": "UNKNOWN: this fixture read the header remotely and "
                           "kept no bytes",
        },
    }
    return rec


FIXTURES = {}

# --- A  a 1.2B whose whole window fits -------------------------------------
FIXTURES["fixture-lfm2-1.2b"] = {
    "machine": REF_3090,
    "what": "A 1.2B hybrid with a 32,768-token window on a 24 GB card. Text "
            "only: no projector, no draft head, no effort knob. The window "
            "fits many times over, so there is no ceiling to find.",
    "models": {
        "Q4_K_M": model(
            "unsloth/LFM2-1.2B-GGUF", "LFM2-1.2B-Q4_K_M.gguf",
            730893024, 1170340608, "lfm2", 32768,
            blocks=16, heads=32, kv_heads=8, head_dim=64, embed=2048,
            full_attn=6, caps=["text"],
            note="lfm2.attention.head_count_kv = [0,0,8,0,0,8,0,0,8,0,8,0,8,0,"
                 "8,0] -- 6 attention blocks of 16, the rest short-convolution"),
    },
}

# --- B  the reference 27B: vision + drafter + effort ------------------------
_Q35 = dict(arch="qwen35", ctx=262144, blocks=65, heads=24, kv_heads=4,
            head_dim=256, embed=5120, full_attn=16,
            caps=["text", "vision", "drafter", "effort"], effort=True,
            vision={"mmproj_file": "mmproj-F16.gguf", "file_bytes": 927607488,
                    "projector_type": "qwen3vl_merger", "supported": True},
            drafter={"file": "MTP/mtp-Qwen3.8-27B-Q4_0.gguf",
                     "file_bytes": 1369590656, "arch": "qwen35",
                     "supported": True},
            note="qwen35 is Gated-DeltaNet + full attention every 4th layer: "
                 "16 full-attention blocks of 65. That is what makes KV 65,536 "
                 "B/token at f16 and 34,816 at q8_0 -- both figures the "
                 "reference campaign measured against the server's own report.")
FIXTURES["fixture-qwen38-27b"] = {
    "machine": REF_3090,
    "what": "The reference campaign's model on the reference card: a 27B "
            "hybrid with a 262,144-token window, an mmproj, an MTP draft head "
            "and a reasoning_effort knob. Everything runs.",
    "models": {
        "UD-Q4_K_M": model("unsloth/Qwen3.8-27B-GGUF",
                           "Qwen3.8-27B-UD-Q4_K_M.gguf",
                           16464440224, 27320697856, **_Q35),
        "UD-IQ4_XS": model("unsloth/Qwen3.8-27B-GGUF",
                           "Qwen3.8-27B-UD-IQ4_XS.gguf",
                           14252845984, 27320697856, **_Q35),
    },
}

# --- C  no drafter, no vision, no effort -- but a ladder --------------------
FIXTURES["fixture-qwen3-30b-a3b-2507"] = {
    "machine": REF_3090,
    "what": "A 30B MoE with a 262,144-token window on the same 24 GB card. No "
            "mmproj in the repo, no MTP sibling, and an instruct template with "
            "no thinking switch: text only. The window does NOT fit, so the "
            "ladder is real -- but three axes of the campaign are gone.",
    "models": {
        "UD-Q4_K_XL": model(
            "unsloth/Qwen3-30B-A3B-Instruct-2507-GGUF",
            "Qwen3-30B-A3B-Instruct-2507-UD-Q4_K_XL.gguf",
            17690497440, 30532122624, "qwen3moe", 262144,
            blocks=48, heads=32, kv_heads=4, head_dim=128, embed=2048,
            full_attn=48, caps=["text"]),
    },
}

# --- D  a 1M-token window against a 24 GB card -----------------------------
FIXTURES["fixture-granite-4.0-h-small"] = {
    "machine": REF_3090,
    "what": "A 32B Granite hybrid whose header declares a 1,048,576-token "
            "window on a card that can hold roughly a third of it. The gap "
            "between what the model offers and what the card holds is the "
            "whole point of deriving rungs.",
    "models": {
        "UD-Q4_K_XL": model(
            "unsloth/granite-4.0-h-small-GGUF",
            "granite-4.0-h-small-UD-Q4_K_XL.gguf",
            18756426656, 32207337984, "granitehybrid", 1048576,
            blocks=40, heads=32, kv_heads=8, head_dim=128, embed=4096,
            full_attn=4, caps=["text"],
            note="granitehybrid.attention.head_count_kv has 8 on blocks 5, 15, "
                 "25 and 35 and 0 on the other 36 -- 4 attention layers of 40, "
                 "which is why a 1M window is even arguable on 24 GB"),
    },
}

# --- E  the SAME 27B, on a 12 GB card --------------------------------------
FIXTURES["fixture-qwen38-27b-12gb"] = {
    "machine": CARD_12GB,
    "what": "Fixture B's files against a 12 GB board. Same model, same "
            "capabilities, different card -- the control for the claim that "
            "the ladder follows the machine and not the model.",
    "models": FIXTURES["fixture-qwen38-27b"]["models"],
}


def write(only=None):
    made = []
    for slug, spec in FIXTURES.items():
        if only and slug not in only:
            continue
        d = os.path.join(RESULTS, slug)
        if os.path.isfile(os.path.join(d, "campaign.md")):
            print("REFUSED %s: it has a campaign.md, so it is a real campaign"
                  % slug)
            continue
        if not os.path.isdir(d):
            os.makedirs(d)
        _dump(os.path.join(d, "machine.json"), spec["machine"])
        for label, rec in spec["models"].items():
            _dump(os.path.join(d, "model-%s.json" % label), rec)
        with io.open(os.path.join(d, "FIXTURE.md"), "w", encoding="utf-8") as fh:
            fh.write("# %s -- FIXTURE, not a campaign\n\n%s\n\n"
                     "Written by scripts/fixtures/plan-campaign-fixtures.py.\n"
                     "Remove with `--clean`.\n" % (slug, spec["what"]))
        made.append(slug)
        print("wrote results/%s/  (machine.json + %d model-*.json)"
              % (slug, len(spec["models"])))
    return made


def clean():
    for slug in FIXTURES:
        d = os.path.join(RESULTS, slug)
        if not os.path.isdir(d):
            continue
        if not os.path.isfile(os.path.join(d, "FIXTURE.md")):
            print("REFUSED %s: no FIXTURE.md, so this script did not write it"
                  % slug)
            continue
        shutil.rmtree(d)
        print("removed results/%s/" % slug)


def _dump(path, obj):
    with io.open(path, "w", encoding="utf-8") as fh:
        fh.write(json.dumps(obj, indent=1))
        fh.write("\n")


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--write", action="store_true")
    ap.add_argument("--clean", action="store_true")
    ap.add_argument("--only", action="append", default=[])
    ap.add_argument("--list", action="store_true")
    a = ap.parse_args()
    if a.list or not (a.write or a.clean):
        for slug, spec in FIXTURES.items():
            print("%-34s %s" % (slug, spec["what"].split(".")[0] + "."))
        return 0
    if a.clean:
        clean()
    if a.write:
        write(a.only or None)
    return 0


if __name__ == "__main__":
    sys.exit(main())
