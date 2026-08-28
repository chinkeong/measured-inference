#!/usr/bin/env python3
"""Regenerate every architect figure for a run, and assemble one report.

    build-report.py --tag iq4xs-agentic --run 2026-08-26-14-57-05--iq4xs-full
    build-report.py --tag q2kxl-agentic --run <dir> --compare iq4xs-agentic

WHAT THIS IS FOR. A measurement campaign accumulates CSVs that nobody can read.
This turns one run's telemetry into the figures a hardware architect actually
uses to decide where to spend silicon, power and engineering effort - and it is
driven entirely from the collected data, so a re-run regenerates the whole
report rather than requiring anyone to remember which chart came from which
column.

HOW MODULES ARE DISCOVERED. Every .py in plots/ that exposes make(ctx, outdir)
is called. A module that raises is REPORTED AND SKIPPED, never silently
dropped: a report missing a figure must say which one and why, because a
quietly shorter report reads exactly like a complete one. That failure mode -
success-shaped, exit 0, plausible output - is the one this campaign keeps
finding, so the driver refuses to participate in it.

THE HTML IS SELF-CONTAINED. Images are inlined as data URIs so the report can
be published, mailed or archived as a single file with no asset directory to
lose.
"""
import argparse, base64, importlib.util, io, json, os, sys, time, traceback

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.join(HERE, "..", "..")
PLOTS = os.path.join(HERE, "plots")
sys.path.insert(0, HERE)

import archdata as A  # noqa: E402


def build_ctx(tag, run):
    """Load every source once. A missing source is None, not an exception:
    figures that need it should degrade and say so on their own face."""
    ctx = {"tag": tag, "run": run}
    for key, fn in (("dmon", lambda: A.load_dmon(tag)),
                    ("slots", lambda: A.load_slots(tag)),
                    ("host", lambda: A.load_host(tag)),
                    ("throttle", lambda: A.load_throttle(tag))):
        try:
            ctx[key] = fn()
        except Exception as e:
            ctx[key] = None
            print("  [ctx] %-9s unavailable: %s" % (key, e))
    ctx["requests"] = A.requests(ctx["slots"]) if ctx.get("slots") is not None else None
    try:
        ctx["exercises"] = A.load_exercises(run) if run else None
    except Exception as e:
        ctx["exercises"] = None
        print("  [ctx] exercises unavailable: %s" % e)
    meta = A.load_runmeta(tag)
    ctx["meta"] = meta
    if meta.get("ctx_tokens") is not None:
        ctx["ctx_tokens"] = meta["ctx_tokens"]
    return ctx


def discover():
    if not os.path.isdir(PLOTS):
        return []
    out = []
    for fn in sorted(os.listdir(PLOTS)):
        if not fn.endswith(".py") or fn.startswith("_"):
            continue
        path = os.path.join(PLOTS, fn)
        name = fn[:-3]
        try:
            spec = importlib.util.spec_from_file_location("plots_" + name, path)
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
        except Exception:
            out.append((name, None, traceback.format_exc(limit=3)))
            continue
        if not hasattr(mod, "make"):
            out.append((name, None, "module has no make(ctx, outdir)"))
            continue
        out.append((name, mod, None))
    return out


def render(tag, run, figures, failures, outdir):
    """One self-contained HTML file. Figures are inlined so nothing can be
    separated from its caption later."""
    parts = []
    for name, png, caption in figures:
        try:
            b = base64.b64encode(io.open(png, "rb").read()).decode("ascii")
        except Exception:
            continue
        parts.append(
            '<figure><img alt="%s" src="data:image/png;base64,%s">'
            '<figcaption><b>%s</b> — %s</figcaption></figure>'
            % (name, b, name, caption or ""))
    fail_html = ""
    if failures:
        rows = "".join("<li><code>%s</code> — %s</li>"
                       % (n, (e or "").strip().splitlines()[-1] if e else "?")
                       for n, e in failures)
        fail_html = ('<section class="warn"><h2>Figures that could not be '
                     'built</h2><p>Listed rather than omitted: a report that '
                     'is quietly shorter reads exactly like a complete one.'
                     '</p><ul>%s</ul></section>' % rows)
    html = """<title>Architect report — %(tag)s</title>
<style>
:root{--bg:#fff;--fg:#16181d;--mut:#5b6270;--line:#e3e6ec;--warn:#8a5a00;--warnbg:#fff8e6}
@media (prefers-color-scheme:dark){:root:not([data-theme="light"]){--bg:#14161a;--fg:#e8eaee;--mut:#9aa3b2;--line:#2a2e37;--warn:#e5b25a;--warnbg:#2a2416}}
:root[data-theme="dark"]{--bg:#14161a;--fg:#e8eaee;--mut:#9aa3b2;--line:#2a2e37;--warn:#e5b25a;--warnbg:#2a2416}
body{background:var(--bg);color:var(--fg);font:16px/1.6 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif;margin:0;padding:2.5rem 1.25rem}
main{max-width:60rem;margin:0 auto}
h1{font-size:1.7rem;margin:0 0 .3rem} h2{font-size:1.15rem;margin:2.5rem 0 .6rem;border-bottom:1px solid var(--line);padding-bottom:.3rem}
.sub{color:var(--mut);margin:0 0 2rem}
figure{margin:0 0 2.5rem} img{max-width:100%%;height:auto;border:1px solid var(--line);border-radius:6px}
figcaption{color:var(--mut);font-size:.9rem;margin-top:.5rem}
.warn{background:var(--warnbg);border-left:3px solid var(--warn);padding:.8rem 1rem;border-radius:4px}
.warn h2{border:0;margin:.2rem 0 .4rem;font-size:1rem;color:var(--warn)}
code{font:.85em ui-monospace,SFMono-Regular,Menlo,monospace}
footer{color:var(--mut);font-size:.85rem;margin-top:3rem;border-top:1px solid var(--line);padding-top:1rem}
</style>
<main>
<h1>Architect report — %(tag)s</h1>
<p class="sub">%(run)s · generated %(when)s · %(n)d figures</p>
%(fail)s
%(figs)s
<footer><b>Instrumentation tier: in-band GPU board power only.</b> The power
supply, CPU, system memory, drives and display are excluded and unmeasured —
nothing here may be called system power. One machine, one GPU vendor, one
runtime. Memory junction temperature and per-process GPU attribution are not
exposed on this part and are absent for that reason, not by omission.</footer>
</main>""" % {"tag": tag, "run": run or "—",
              "when": time.strftime("%Y-%m-%d %H:%M"),
              "n": len(parts), "fail": fail_html, "figs": "\n".join(parts)}
    path = os.path.join(outdir, "report-%s.html" % tag)
    io.open(path, "w", encoding="utf-8").write(html)
    return path


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--tag", required=True)
    ap.add_argument("--run", default=None)
    ap.add_argument("--outdir", default=None)
    a = ap.parse_args()

    # PER-TAG output. Every tag used to render into ONE directory under the
    # same 19 filenames, so two builds a minute apart silently overwrote each
    # other and the surviving set was whichever build wrote each file last -
    # unrecorded, and not the same run for every figure. The published set was
    # exactly that: capacity-vram-ceiling.png shows a 17,410 MiB median for the
    # 4-bit arm and 13,417 MiB for the 2-bit one, and nothing on disk said
    # which was on the page. A figure that cannot name its run is not evidence.
    outdir = a.outdir or os.path.join(ROOT, "results", "qwen38-27b-blind",
                                      "figures", a.tag)
    if not os.path.isdir(outdir):
        os.makedirs(outdir)

    print("loading telemetry for %s" % a.tag)
    ctx = build_ctx(a.tag, a.run)
    for k in ("dmon", "slots", "host", "throttle"):
        v = ctx.get(k)
        n = len(v["t"]) if isinstance(v, dict) and "t" in v else 0
        print("  %-9s %d samples" % (k, n))
    if ctx.get("requests"):
        print("  requests  %d" % len(ctx["requests"]))
    if ctx.get("exercises"):
        print("  exercises %d" % len(ctx["exercises"]))
    meta = ctx.get("meta")
    if meta:
        src = ("read from server log" if meta.get("log")
               else ("inferred from tag" if meta.get("inferred_from_tag")
                     else "not recorded"))
        n_missing = len(meta.get("flags_missing", []))
        print("  model     %s (%s, %d flags unrecorded)"
              % (meta.get("model_label") or "unknown", src, n_missing))
    else:
        print("  model     no run metadata available")

    mods = discover()
    if not mods:
        sys.exit("no plot modules found in %s" % PLOTS)

    figures, failures = [], []
    for name, mod, err in mods:
        if mod is None:
            failures.append((name, err))
            print("  [FAIL] %-12s %s" % (name, (err or "").strip().splitlines()[-1]))
            continue
        try:
            got = mod.make(ctx, outdir) or []
        except Exception:
            failures.append((name, traceback.format_exc(limit=4)))
            print("  [FAIL] %-12s raised" % name)
            continue
        made = 0
        for item in got:
            png, cap = (item if isinstance(item, (tuple, list)) and len(item) == 2
                        else (item, ""))
            # A figure file that does not exist, or is trivially small, is a
            # failure wearing a success's clothes.
            if not (png and os.path.exists(png) and os.path.getsize(png) > 4096):
                failures.append((name, "produced no usable PNG: %s" % png))
                continue
            figures.append((name, png, cap))
            made += 1
        print("  [ ok ] %-12s %d figure(s)" % (name, made))

    path = render(a.tag, a.run, figures, failures, outdir)
    json.dump({"tag": a.tag, "run": a.run,
               "figures": [{"module": n, "png": os.path.basename(p),
                            "caption": c} for n, p, c in figures],
               "failures": [{"module": n, "error": (e or "")[-400:]}
                            for n, e in failures],
               "generated": time.strftime("%Y-%m-%d %H:%M")},
              io.open(os.path.join(outdir, "manifest-%s.json" % a.tag), "w",
                      encoding="utf-8"), indent=1)
    print()
    print("report: %s" % path)
    print("%d figures, %d failures" % (len(figures), len(failures)))
    if failures:
        print("FAILURES ARE LISTED IN THE REPORT, not omitted from it.")
