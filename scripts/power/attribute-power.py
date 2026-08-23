#!/usr/bin/env python3
"""attribute-power.py - join an nvidia-smi power CSV to inference work and emit
energy metrics per label.

TIER: every number here is IN-BAND GPU BOARD POWER (NVML, as reported by
nvidia-smi). PSU conversion losses, CPU/RAM/fans/drives, and datacentre PUE are
NOT included and are unmeasured unless a wall meter or PDU was logged too.
Never call this "system power".

Two attribution modes:

  --events <jsonl>   one line per request:
                     {"t_start_iso": "...", "prompt_ms": 1234.5,
                      "predicted_ms": 60000.0, "prompt_n": 1500,
                      "predicted_n": 700, "label": "spec-n4"}
                     Gives a real PREFILL/DECODE split, because the server's own
                     timings say where the boundary is.

  --window T0 T1 LABEL   coarse per-arm attribution when you only know when an
                     arm started and stopped. No phase split; J/token only if
                     you also pass --label-tokens.

Both modes can be combined. Output: per-label J, Wh, mean W, J/decode-token,
J/prompt-token, tokens/kWh, EDP (J.s), gross and idle-subtracted.

Stdlib only. Python 3.8+.
"""

import argparse
import bisect
import datetime as dt
import json
import math
import os
import sys

# --------------------------------------------------------------------------
# CSV loading
# --------------------------------------------------------------------------

TS_FORMATS = (
    "%Y/%m/%d %H:%M:%S.%f",
    "%Y/%m/%d %H:%M:%S",
    "%Y-%m-%d %H:%M:%S.%f",
    "%Y-%m-%d %H:%M:%S",
)


def parse_ts(s):
    """nvidia-smi's local, naive timestamp."""
    s = s.strip()
    for f in TS_FORMATS:
        try:
            return dt.datetime.strptime(s, f)
        except ValueError:
            pass
    # last resort: ISO
    try:
        d = dt.datetime.fromisoformat(s.replace("Z", "+00:00"))
        if d.tzinfo is not None:
            d = d.astimezone().replace(tzinfo=None)
        return d
    except Exception:
        return None


def parse_iso(s):
    """Event timestamps. Naive means local, matching nvidia-smi."""
    s = str(s).strip()
    try:
        d = dt.datetime.fromisoformat(s.replace("Z", "+00:00"))
    except Exception:
        d = parse_ts(s)
        if d is None:
            raise ValueError("unparseable timestamp: %r" % s)
        return d
    if d.tzinfo is not None:
        d = d.astimezone().replace(tzinfo=None)
    return d


def strip_units(tok):
    """'349.26' -> 349.26 ; ' 98.71 W' -> 98.71 ; '[N/A]' -> None."""
    t = tok.strip()
    if not t or t.startswith("[") or t.upper() in ("N/A", "NA", "-"):
        return None
    # keep leading number, drop any trailing unit suffix
    out = []
    for ch in t:
        if ch.isdigit() or ch in ".-+eE":
            out.append(ch)
        else:
            break
    try:
        return float("".join(out))
    except ValueError:
        return None


def load_power(paths, power_col=None, use_instant=False):
    """Return (samples, meta). samples = sorted list of (datetime, watts)."""
    samples = []
    meta = {"files": [], "header": None, "power_column": None, "skipped": 0}
    for path in paths:
        n_rows = 0
        col = power_col
        # utf-8-sig: PowerShell 5.1 writes UTF-8 files with a BOM.
        with open(path, "r", encoding="utf-8-sig", errors="replace") as fh:
            for line in fh:
                parts = [p.strip().lstrip("﻿") for p in line.split(",")]
                if len(parts) < 2:
                    continue
                low = parts[0].lower()
                if low.startswith("timestamp") or low.startswith("#"):
                    # header row - use it to find the power column by name
                    meta["header"] = [p for p in parts]
                    if power_col is None:
                        want = "power.draw.instant" if use_instant else "power.draw"
                        best = None
                        for i, name in enumerate(parts):
                            nm = name.split("[")[0].strip().lower()
                            if nm == want:
                                best = i
                                break
                        if best is None:
                            for i, name in enumerate(parts):
                                if name.lower().startswith("power.draw"):
                                    best = i
                                    break
                        col = best if best is not None else 1
                    continue
                if col is None:
                    # headerless file: nvidia-smi puts power right after timestamp
                    col = 2 if (use_instant and len(parts) > 2) else 1
                t = parse_ts(parts[0])
                if t is None:
                    meta["skipped"] += 1
                    continue
                if col >= len(parts):
                    meta["skipped"] += 1
                    continue
                w = strip_units(parts[col])
                if w is None:
                    meta["skipped"] += 1
                    continue
                samples.append((t, w))
                n_rows += 1
        meta["files"].append({"path": os.path.abspath(path), "rows": n_rows})
        meta["power_column"] = col
    samples.sort(key=lambda r: r[0])
    # de-duplicate identical timestamps (two logs overlapping)
    dedup = []
    last = None
    for t, w in samples:
        if last is not None and t == last:
            continue
        dedup.append((t, w))
        last = t
    return dedup, meta


# --------------------------------------------------------------------------
# integration
# --------------------------------------------------------------------------


class PowerSeries(object):
    """Trapezoidal integration of W over time, with a hard cap on the segment
    length so a logger restart (or a laptop sleep) cannot fabricate energy."""

    def __init__(self, samples, max_gap=2.0):
        if not samples:
            raise ValueError("no power samples")
        self.ref = samples[0][0]
        self.x = [(t - self.ref).total_seconds() for t, _ in samples]
        self.y = [w for _, w in samples]
        self.max_gap = float(max_gap)
        self.t0 = samples[0][0]
        self.t1 = samples[-1][0]

    def _rel(self, when):
        return (when - self.ref).total_seconds()

    def integrate(self, a, b):
        """a, b: datetimes. Returns a dict of the raw integration facts."""
        xa, xb = self._rel(a), self._rel(b)
        if xb < xa:
            xa, xb = xb, xa
        joules = 0.0
        covered = 0.0
        excluded = 0.0
        peak = None
        n_in = 0
        x, y, cap = self.x, self.y, self.max_gap

        i = bisect.bisect_right(x, xa) - 1
        if i < 0:
            i = 0
        while i < len(x) - 1:
            sa, sb = x[i], x[i + 1]
            if sa >= xb:
                break
            if sb <= xa:
                i += 1
                continue
            wa, wb = y[i], y[i + 1]
            seg = sb - sa
            c0 = max(sa, xa)
            c1 = min(sb, xb)
            width = c1 - c0
            if width > 0:
                if seg <= cap and seg > 0:
                    fa = (c0 - sa) / seg
                    fb = (c1 - sa) / seg
                    w0 = wa + (wb - wa) * fa
                    w1 = wa + (wb - wa) * fb
                    joules += 0.5 * (w0 + w1) * width
                    covered += width
                    hi = max(w0, w1)
                else:
                    # gap: credit at most `cap` seconds, at the endpoint mean,
                    # and account for the rest as uncovered time.
                    allow = min(width, cap)
                    mean = 0.5 * (wa + wb)
                    joules += mean * allow
                    covered += allow
                    excluded += width - allow
                    hi = mean
                peak = hi if peak is None else max(peak, hi)
            i += 1

        for j in range(len(x)):
            if x[j] > xb:
                break
            if x[j] >= xa:
                n_in += 1
                peak = y[j] if peak is None else max(peak, y[j])

        window_s = xb - xa
        return {
            "window_s": window_s,
            "covered_s": covered,
            "excluded_s": excluded,
            "coverage": (covered / window_s) if window_s > 0 else 0.0,
            "joules": joules,
            "mean_w": (joules / covered) if covered > 0 else None,
            "peak_w": peak,
            "n_samples": n_in,
        }


# --------------------------------------------------------------------------
# metric assembly
# --------------------------------------------------------------------------


def blank_arm(label):
    return {
        "label": label,
        "n_requests": 0,
        "mode": None,
        "window_s": 0.0,
        "covered_s": 0.0,
        "excluded_s": 0.0,
        "n_samples": 0,
        "peak_w": None,
        "j_prefill": 0.0,
        "j_decode": 0.0,
        "j_total": 0.0,
        "prefill_s": 0.0,
        "decode_s": 0.0,
        "prompt_n": 0,
        "predicted_n": 0,
        "edp_sum": 0.0,
        "warnings": [],
    }


def finish_arm(a, idle_w):
    cov = a["covered_s"]
    n = max(a["n_requests"], 1)
    j_gross = a["j_total"]
    j_net = j_gross - idle_w * cov
    dec_cov = a["decode_s"]
    pre_cov = a["prefill_s"]
    j_dec_net = a["j_decode"] - idle_w * dec_cov if dec_cov > 0 else None
    j_pre_net = a["j_prefill"] - idle_w * pre_cov if pre_cov > 0 else None

    out = dict(a)
    out["mean_w"] = (j_gross / cov) if cov > 0 else None
    out["coverage"] = (cov / a["window_s"]) if a["window_s"] > 0 else 0.0
    out["j_gross"] = j_gross
    out["j_net"] = j_net
    out["wh_gross"] = j_gross / 3600.0
    out["wh_net"] = j_net / 3600.0
    out["wh_per_answer_gross"] = j_gross / 3600.0 / n
    out["wh_per_answer_net"] = j_net / 3600.0 / n
    out["j_net_decode"] = j_dec_net
    out["j_net_prefill"] = j_pre_net

    pn = a["predicted_n"]
    qn = a["prompt_n"]
    out["j_per_decode_token"] = (a["j_decode"] / pn) if (pn and a["j_decode"]) else None
    out["j_per_decode_token_net"] = (j_dec_net / pn) if (pn and j_dec_net is not None) else None
    out["j_per_prompt_token"] = (a["j_prefill"] / qn) if (qn and a["j_prefill"]) else None
    out["j_per_prompt_token_net"] = (j_pre_net / qn) if (qn and j_pre_net is not None) else None
    out["tokens_per_kwh"] = (pn / (a["j_decode"] / 3.6e6)) if (pn and a["j_decode"] > 0) else None
    out["tokens_per_kwh_net"] = (pn / (j_dec_net / 3.6e6)) if (pn and j_dec_net and j_dec_net > 0) else None
    out["decode_tps"] = (pn / dec_cov) if (pn and dec_cov > 0) else None
    out["prefill_tps"] = (qn / pre_cov) if (qn and pre_cov > 0) else None
    # EDP: SKILL convention is J_decode x decode-seconds, per request, averaged.
    out["edp_js"] = (a["edp_sum"] / n) if a["edp_sum"] else None
    out["edp_total_js"] = j_gross * (a["window_s"] / n) if a["window_s"] else None
    out["idle_w_used"] = idle_w
    return out


def attribute_events(series, events, idle_w, lead_ms, drop_first, arms, notes=None):
    seen = {}
    dropped = {}
    for ev in events:
        label = ev.get("label") or "unlabelled"
        idx = seen.get(label, 0)
        seen[label] = idx + 1
        if drop_first and idx == 0:
            dropped[label] = dropped.get(label, 0) + 1
            continue
        t0 = parse_iso(ev["t_start_iso"]) + dt.timedelta(milliseconds=float(lead_ms))
        pm = ev.get("prompt_ms")
        dm = ev.get("predicted_ms")
        a = arms.setdefault(label, blank_arm(label))
        a["n_requests"] += 1
        a["mode"] = "events" if a["mode"] in (None, "events") else "mixed"

        if pm is None or dm is None:
            # no timings -> treat the whole recorded span as one undivided window
            end = ev.get("t_end_iso")
            if end is None:
                a["warnings"].append("event without timings and without t_end_iso skipped")
                a["n_requests"] -= 1
                continue
            r = series.integrate(t0, parse_iso(end))
            a["window_s"] += r["window_s"]
            a["covered_s"] += r["covered_s"]
            a["excluded_s"] += r["excluded_s"]
            a["n_samples"] += r["n_samples"]
            a["j_total"] += r["joules"]
            if r["peak_w"] is not None:
                a["peak_w"] = r["peak_w"] if a["peak_w"] is None else max(a["peak_w"], r["peak_w"])
            a["warnings"].append("no prompt_ms/predicted_ms: no phase split for this request")
            continue

        t_split = t0 + dt.timedelta(milliseconds=float(pm))
        t_end = t_split + dt.timedelta(milliseconds=float(dm))
        rp = series.integrate(t0, t_split)
        rd = series.integrate(t_split, t_end)

        a["j_prefill"] += rp["joules"]
        a["j_decode"] += rd["joules"]
        a["j_total"] += rp["joules"] + rd["joules"]
        a["prefill_s"] += rp["covered_s"]
        a["decode_s"] += rd["covered_s"]
        a["window_s"] += rp["window_s"] + rd["window_s"]
        a["covered_s"] += rp["covered_s"] + rd["covered_s"]
        a["excluded_s"] += rp["excluded_s"] + rd["excluded_s"]
        a["n_samples"] += rp["n_samples"] + rd["n_samples"]
        a["prompt_n"] += int(ev.get("prompt_n") or 0)
        a["predicted_n"] += int(ev.get("predicted_n") or 0)
        a["edp_sum"] += rd["joules"] * rd["covered_s"]
        for r in (rp, rd):
            if r["peak_w"] is not None:
                a["peak_w"] = r["peak_w"] if a["peak_w"] is None else max(a["peak_w"], r["peak_w"])
        if rp["n_samples"] == 0 and rp["window_s"] > 0:
            a["warnings"].append(
                "prefill window %.2fs shorter than the sample period - "
                "J_prefill is interpolated, not sampled" % rp["window_s"])

    if notes is not None:
        for label, n in sorted(dropped.items()):
            if seen.get(label, 0) <= n:
                notes.append("--drop-first removed the ONLY request of label %r - "
                             "that arm is absent from the tables below, not zero" % label)
    return arms


def attribute_windows(series, windows, label_tokens, arms):
    for t0s, t1s, label in windows:
        t0, t1 = parse_iso(t0s), parse_iso(t1s)
        r = series.integrate(t0, t1)
        a = arms.setdefault(label, blank_arm(label))
        a["n_requests"] += 1
        a["mode"] = "windows" if a["mode"] in (None, "windows") else "mixed"
        a["window_s"] += r["window_s"]
        a["covered_s"] += r["covered_s"]
        a["excluded_s"] += r["excluded_s"]
        a["n_samples"] += r["n_samples"]
        a["j_total"] += r["joules"]
        if r["peak_w"] is not None:
            a["peak_w"] = r["peak_w"] if a["peak_w"] is None else max(a["peak_w"], r["peak_w"])
        tk = label_tokens.get(label)
        if tk:
            dec, pro = tk
            a["predicted_n"] += dec
            a["prompt_n"] += pro
            # No timings: the whole window is charged to decode, which is the
            # honest reading of a coarse arm dominated by generation.
            a["j_decode"] += r["joules"]
            a["decode_s"] += r["covered_s"]
            a["edp_sum"] += r["joules"] * r["covered_s"]
            a["warnings"].append(
                "coarse window: prefill and decode are NOT separated; "
                "J/decode-token here includes prefill energy")
    return arms


# --------------------------------------------------------------------------
# rendering
# --------------------------------------------------------------------------


def f(v, spec="%.2f"):
    if v is None:
        return "n/a"
    if isinstance(v, float) and (math.isnan(v) or math.isinf(v)):
        return "n/a"
    return spec % v


def render_text(rows, meta, args, notes=None):
    L = []
    L.append("=" * 78)
    L.append("ENERGY ATTRIBUTION - in-band GPU board power (NVML via nvidia-smi)")
    L.append("PSU losses, rest-of-node and PUE are EXCLUDED and unmeasured.")
    L.append("=" * 78)
    for fi in meta["files"]:
        L.append("power log : %s  (%d usable rows)" % (fi["path"], fi["rows"]))
    if meta.get("span"):
        L.append("log span  : %s .. %s" % meta["span"])
    L.append("power col : index %s%s" % (meta["power_column"],
                                         " (power.draw.instant)" if args.use_instant else " (power.draw)"))
    L.append("idle W    : %.2f  (flag --idle-w; loaded-idle reference on this box 30.7-31.1 W)" % args.idle_w)
    L.append("max gap   : %.1f s (segments longer than this are credited at most %.1f s)"
             % (args.max_gap, args.max_gap))
    if args.lead_ms:
        L.append("lead      : %+.0f ms applied to every t_start_iso" % args.lead_ms)
    L.append("")

    hdr = ("%-22s %4s %9s %6s %8s %8s %11s %9s %11s %9s"
           % ("label", "n", "wall_s", "cov%", "mean_W", "peak_W",
              "J_gross", "Wh_gross", "J_net", "Wh_net"))
    L.append("--- ARM SUMMARY " + "-" * (len(hdr) - 16))
    L.append(hdr)
    for r in rows:
        L.append("%-22s %4d %9.2f %5.1f%% %8s %8s %11.1f %9.4f %11.1f %9.4f"
                 % (r["label"][:22], r["n_requests"], r["window_s"], r["coverage"] * 100.0,
                    f(r["mean_w"], "%.1f"), f(r["peak_w"], "%.1f"),
                    r["j_gross"], r["wh_gross"], r["j_net"], r["wh_net"]))
    L.append("")

    hdr2 = ("%-22s %9s %10s %13s %9s %10s %11s %12s %12s"
            % ("label", "prefill_s", "J_prefill", "J/prompt_tok", "decode_s",
               "J_decode", "J/dec_tok", "tokens/kWh", "EDP_J.s"))
    L.append("--- PHASE ATTRIBUTION " + "-" * (len(hdr2) - 22))
    L.append(hdr2)
    for r in rows:
        L.append("%-22s %9.2f %10.1f %13s %9.2f %10.1f %11s %12s %12s"
                 % (r["label"][:22], r["prefill_s"], r["j_prefill"],
                    f(r["j_per_prompt_token"], "%.4f"), r["decode_s"], r["j_decode"],
                    f(r["j_per_decode_token"], "%.3f"), f(r["tokens_per_kwh"], "%.0f"),
                    f(r["edp_js"], "%.0f")))
    L.append("")

    hdr3 = ("%-22s %12s %12s %14s %12s %12s"
            % ("label", "dec_tok/s", "J/dec_tok", "J/dec_tok_net", "tok/kWh_net", "Wh/answer"))
    L.append("--- IDLE-SUBTRACTED (idle %.1f W removed over covered seconds) %s"
             % (args.idle_w, "-" * 12))
    L.append(hdr3)
    for r in rows:
        L.append("%-22s %12s %12s %14s %12s %12s"
                 % (r["label"][:22], f(r["decode_tps"], "%.2f"),
                    f(r["j_per_decode_token"], "%.3f"), f(r["j_per_decode_token_net"], "%.3f"),
                    f(r["tokens_per_kwh_net"], "%.0f"), f(r["wh_per_answer_gross"], "%.3f")))
    L.append("")

    warn = list(notes or [])
    for r in rows:
        if r["coverage"] < args.min_coverage:
            warn.append("%s: only %.1f%% of the window has power samples "
                        "(%.1fs uncovered) - the log was not running for all of it"
                        % (r["label"], r["coverage"] * 100.0, r["excluded_s"]))
        if r["n_samples"] < 4 and r["window_s"] > 0:
            warn.append("%s: %d samples in window - too few to trust a mean"
                        % (r["label"], r["n_samples"]))
        for w in dict.fromkeys(r["warnings"]):
            warn.append("%s: %s" % (r["label"], w))
    if warn:
        L.append("--- WARNINGS " + "-" * 60)
        for w in warn:
            L.append("  ! " + w)
        L.append("")
    L.append("CAVEAT clock-ramp: a request issued on a cold/idle board runs at a reduced SM")
    L.append("clock for its first seconds (measured here: 900-990 MHz vs 1455 settled), so")
    L.append("its watts read LOW and its J/token reads misleadingly good. Drop the first")
    L.append("request of every arm (--drop-first) or warm the board first.")
    return "\n".join(L)


def to_csv(rows, path):
    cols = ["label", "n_requests", "mode", "window_s", "covered_s", "coverage",
            "n_samples", "mean_w", "peak_w", "j_gross", "wh_gross", "j_net", "wh_net",
            "j_prefill", "j_decode", "prefill_s", "decode_s", "prompt_n", "predicted_n",
            "j_per_prompt_token", "j_per_decode_token", "j_per_decode_token_net",
            "tokens_per_kwh", "tokens_per_kwh_net", "decode_tps", "edp_js",
            "wh_per_answer_gross", "wh_per_answer_net", "idle_w_used"]
    with open(path, "w", encoding="utf-8", newline="") as fh:
        fh.write(",".join(cols) + "\n")
        for r in rows:
            vals = []
            for c in cols:
                v = r.get(c)
                if v is None:
                    vals.append("")
                elif isinstance(v, float):
                    vals.append("%.6g" % v)
                else:
                    vals.append(str(v))
            fh.write(",".join(vals) + "\n")


# --------------------------------------------------------------------------
# selftest
# --------------------------------------------------------------------------


def _mk(samples_wh, start=None, step=0.5):
    """[(seconds, watts)] -> [(datetime, watts)]"""
    base = start or dt.datetime(2026, 8, 23, 12, 0, 0)
    return [(base + dt.timedelta(seconds=s), w) for s, w in samples_wh]


def selftest():
    fails = []

    def check(name, got, want, tol=1e-6):
        ok = (got is not None) and abs(got - want) <= tol
        print("  %-52s %s  (got %s, want %s)"
              % (name, "PASS" if ok else "FAIL", f(got, "%.6f"), f(want, "%.6f")))
        if not ok:
            fails.append(name)

    base = dt.datetime(2026, 8, 23, 12, 0, 0)

    print("selftest 1: constant 100 W for 10 s == 1000 J")
    s = _mk([(i * 0.5, 100.0) for i in range(21)], base)
    ps = PowerSeries(s, max_gap=2.0)
    r = ps.integrate(base, base + dt.timedelta(seconds=10))
    check("J over [0,10]", r["joules"], 1000.0)
    check("covered_s", r["covered_s"], 10.0)
    check("mean_W", r["mean_w"], 100.0)
    check("coverage", r["coverage"], 1.0)

    print("selftest 2: trapezoid on a ramp, sub-sample window edges")
    # w(t) = 100 + 10*t  ->  integral 2.5..7.5 = 100*5 + 5*(7.5^2-2.5^2) = 750
    s = _mk([(i * 0.5, 100.0 + 10.0 * (i * 0.5)) for i in range(21)], base)
    ps = PowerSeries(s, max_gap=2.0)
    r = ps.integrate(base + dt.timedelta(seconds=2.5), base + dt.timedelta(seconds=7.5))
    check("J over [2.5,7.5] of 100+10t", r["joules"], 750.0, tol=1e-6)

    print("selftest 3: a 10 s hole is capped at max_gap=2 s, not integrated whole")
    s = _mk([(0.0, 100.0), (10.0, 100.0)], base)
    ps = PowerSeries(s, max_gap=2.0)
    r = ps.integrate(base, base + dt.timedelta(seconds=10))
    check("J across the hole", r["joules"], 200.0)
    check("excluded_s", r["excluded_s"], 8.0)
    check("coverage", r["coverage"], 0.2)

    print("selftest 4: prefill/decode split + per-phase metrics")
    # 0-2 s at 200 W (prefill), 2-10 s at 100 W (decode). The step is expressed
    # as two samples 1 us apart, because that is the shape a real log can hold
    # (identical timestamps get de-duplicated on load). That 1 us costs ~50 uJ
    # out of 1200 J, so the checks below are exact to ~1e-7 relative, not to
    # the last float bit.
    pts = [(0.0, 200.0), (0.5, 200.0), (1.0, 200.0), (1.5, 200.0), (2.0, 200.0)] + \
          [(2.0 + 1e-6, 100.0)] + [(2.0 + 0.5 * i, 100.0) for i in range(1, 17)]
    s = _mk(pts, base)
    ps = PowerSeries(s, max_gap=2.0)
    arms = {}
    ev = [{"t_start_iso": base.isoformat(timespec="milliseconds"),
           "prompt_ms": 2000.0, "predicted_ms": 8000.0,
           "prompt_n": 100, "predicted_n": 80, "label": "synthetic"}]
    attribute_events(ps, ev, 31.0, 0.0, False, arms)
    out = finish_arm(arms["synthetic"], 31.0)
    check("J_prefill (200 W x 2 s)", out["j_prefill"], 400.0, tol=1e-3)
    check("J_decode  (100 W x 8 s)", out["j_decode"], 800.0, tol=1e-3)
    check("J_total", out["j_gross"], 1200.0, tol=1e-3)
    check("J per prompt-token (400/100)", out["j_per_prompt_token"], 4.0, tol=1e-5)
    check("J per decode-token (800/80)", out["j_per_decode_token"], 10.0, tol=1e-5)
    check("tokens/kWh (80 / 800 J)", out["tokens_per_kwh"], 80.0 / (800.0 / 3.6e6), tol=1.0)
    check("EDP = J_decode x decode_s", out["edp_js"], 800.0 * 8.0, tol=1e-1)
    check("Wh gross", out["wh_gross"], 1200.0 / 3600.0, tol=1e-6)
    check("decode tok/s", out["decode_tps"], 10.0, tol=1e-6)

    print("selftest 5: idle subtraction (idle 31 W over the covered 10 s)")
    check("J_net = 1200 - 31*10", out["j_net"], 1200.0 - 310.0, tol=1e-3)
    check("J/dec_tok_net = (800-31*8)/80", out["j_per_decode_token_net"],
          (800.0 - 31.0 * 8.0) / 80.0, tol=1e-5)

    print("selftest 6: CSV parsing - header row, units-stripped, unit-suffixed, [N/A]")
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        p1 = os.path.join(td, "nounits.csv")
        with open(p1, "w", encoding="utf-8") as fh:
            fh.write("timestamp, power.draw [W], power.draw.instant [W], clocks.sm [MHz], pstate\n")
            fh.write("2026/08/23 12:00:00.000, 349.26, 349.61, 1635, P2\n")
            fh.write("2026/08/23 12:00:00.500, [N/A], 348.88, 1635, P2\n")
            fh.write("2026/08/23 12:00:01.000, 351.00, 350.10, 1650, P2\n")
        sm, mt = load_power([p1])
        check("rows parsed (N/A dropped)", float(len(sm)), 2.0)
        check("power column found by header name", float(mt["power_column"]), 1.0)
        check("first watt value", sm[0][1], 349.26, tol=1e-9)

        p2 = os.path.join(td, "units.csv")
        with open(p2, "w", encoding="utf-8") as fh:
            fh.write("2026/08/23 00:54:46.429, 98.71 W, 3 %, 433 MiB\n")
            fh.write("2026/08/23 00:54:47.439, 86.93 W, 6 %, 433 MiB\n")
        sm2, _ = load_power([p2])
        check("headerless + unit suffix", sm2[0][1], 98.71, tol=1e-9)
        check("headerless row count", float(len(sm2)), 2.0)

    print("selftest 7: coarse --window mode with --label-tokens")
    s = _mk([(i * 0.5, 344.0) for i in range(41)], base)
    ps = PowerSeries(s, max_gap=2.0)
    arms = {}
    attribute_windows(ps,
                      [(base.isoformat(timespec="milliseconds"),
                        (base + dt.timedelta(seconds=20)).isoformat(timespec="milliseconds"),
                        "arm-a")],
                      {"arm-a": (700, 1500)}, arms)
    out = finish_arm(arms["arm-a"], 31.0)
    check("J over 20 s at 344 W", out["j_gross"], 344.0 * 20.0, tol=1e-6)
    check("Wh", out["wh_gross"], 344.0 * 20.0 / 3600.0, tol=1e-9)
    check("J/decode-token (coarse)", out["j_per_decode_token"], 344.0 * 20.0 / 700.0, tol=1e-6)

    print("")
    if fails:
        print("SELFTEST FAILED: %d check(s): %s" % (len(fails), ", ".join(fails)))
        return 1
    print("SELFTEST PASSED (all checks)")
    return 0


# --------------------------------------------------------------------------
# main
# --------------------------------------------------------------------------


def main(argv):
    ap = argparse.ArgumentParser(
        description="Attribute GPU board energy to labelled inference work.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__)
    ap.add_argument("--power", action="append", default=[], metavar="CSV",
                    help="nvidia-smi power CSV (repeatable; logs are merged and sorted)")
    ap.add_argument("--events", action="append", default=[], metavar="JSONL",
                    help="request-event JSONL from capture-request.ps1 (repeatable)")
    ap.add_argument("--window", action="append", nargs=3, default=[],
                    metavar=("T0", "T1", "LABEL"),
                    help="coarse window: two ISO timestamps and a label (repeatable)")
    ap.add_argument("--label-tokens", action="append", default=[], metavar="L=DEC[/PROMPT]",
                    help="token counts for a coarse --window label, e.g. spec-n4=700/1500")
    ap.add_argument("--idle-w", type=float, default=31.0,
                    help="idle board watts to subtract for the 'net' columns (default 31.0, "
                         "the loaded-idle figure measured on this 3090)")
    ap.add_argument("--max-gap", type=float, default=2.0,
                    help="cap on a single sample interval in seconds (default 2.0); longer "
                         "segments are credited at most this much so a logger restart cannot "
                         "fabricate energy")
    ap.add_argument("--lead-ms", type=float, default=0.0,
                    help="shift every t_start_iso by this many ms before splitting phases. "
                         "t_start is stamped client-side BEFORE the POST, so HTTP + queue "
                         "latency sits inside the prefill window; use this to correct it.")
    ap.add_argument("--drop-first", action="store_true",
                    help="drop the first request of every label (the clock-ramp victim)")
    ap.add_argument("--use-instant", action="store_true",
                    help="integrate power.draw.instant instead of power.draw")
    ap.add_argument("--power-col", type=int, default=None,
                    help="force the 0-based power column index")
    ap.add_argument("--min-coverage", type=float, default=0.9,
                    help="warn below this covered/window fraction (default 0.9)")
    ap.add_argument("--json", metavar="PATH", help="write machine-readable JSON here")
    ap.add_argument("--csv-out", metavar="PATH", help="write a flat CSV of the arm rows here")
    ap.add_argument("--quiet", action="store_true", help="suppress the text report")
    ap.add_argument("--selftest", action="store_true",
                    help="run synthetic-data assertions and exit")
    args = ap.parse_args(argv)

    if args.selftest:
        return selftest()

    if not args.power:
        ap.error("--power is required (or use --selftest)")
    if not args.events and not args.window:
        ap.error("give at least one --events JSONL or one --window T0 T1 LABEL")

    samples, meta = load_power(args.power, args.power_col, args.use_instant)
    if not samples:
        print("ERROR no usable power samples in: %s" % ", ".join(args.power), file=sys.stderr)
        return 2
    meta["span"] = (samples[0][0].isoformat(sep=" "), samples[-1][0].isoformat(sep=" "))
    series = PowerSeries(samples, max_gap=args.max_gap)

    label_tokens = {}
    for spec in args.label_tokens:
        if "=" not in spec:
            ap.error("--label-tokens wants LABEL=DEC[/PROMPT], got %r" % spec)
        lab, rhs = spec.split("=", 1)
        if "/" in rhs:
            d, p = rhs.split("/", 1)
        else:
            d, p = rhs, "0"
        label_tokens[lab.strip()] = (int(d), int(p))

    events = []
    for path in args.events:
        with open(path, "r", encoding="utf-8-sig") as fh:
            for ln, line in enumerate(fh, 1):
                line = line.strip().lstrip("﻿")
                if not line or line.startswith("#"):
                    continue
                try:
                    events.append(json.loads(line))
                except json.JSONDecodeError as e:
                    print("WARN %s:%d unparseable JSONL line skipped (%s)"
                          % (path, ln, e), file=sys.stderr)
    events.sort(key=lambda e: str(e.get("t_start_iso", "")))

    arms = {}
    notes = []
    if events:
        attribute_events(series, events, args.idle_w, args.lead_ms, args.drop_first,
                         arms, notes)
    if args.window:
        attribute_windows(series, args.window, label_tokens, arms)

    rows = [finish_arm(a, args.idle_w) for a in arms.values()]
    rows.sort(key=lambda r: r["label"])

    if not args.quiet:
        print(render_text(rows, meta, args, notes))

    if args.json:
        payload = {
            "tier": "in-band GPU board power (NVML via nvidia-smi); PSU/wall/PUE excluded",
            "generated": dt.datetime.now().isoformat(timespec="seconds"),
            "power_files": meta["files"],
            "log_span": meta["span"],
            "idle_w": args.idle_w,
            "max_gap_s": args.max_gap,
            "lead_ms": args.lead_ms,
            "drop_first": args.drop_first,
            "arms": rows,
        }
        with open(args.json, "w", encoding="utf-8") as fh:
            json.dump(payload, fh, indent=2)
        print("wrote %s" % args.json)
    if args.csv_out:
        to_csv(rows, args.csv_out)
        print("wrote %s" % args.csv_out)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
