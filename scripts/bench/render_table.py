"""Render benchmark results as a dark table PNG.

Usage:
    python render_table.py results/<run>.json            # render one run file
    python render_table.py results/a.json results/b.json # merge runs -> one comparison table
    python render_table.py --latest                      # newest run in results/
"""

import glob
import json
import os
import sys

from PIL import Image, ImageDraw, ImageFont

HERE = os.path.dirname(os.path.abspath(__file__))

# ---- style constants ----
BG = (10, 10, 10)
CARD = (17, 17, 18)
BORDER = (38, 38, 40)
ROW_LINE = (32, 32, 34)
HEADER_FG = (235, 235, 235)
DIM_FG = (140, 140, 145)
BRIGHT_FG = (250, 250, 250)
CAPTION_FG = (150, 150, 155)

SCALE = 2  # supersample for crisp text


def _font(size, bold=False):
    names = (["segoeuib.ttf", "arialbd.ttf"] if bold else ["segoeui.ttf", "arial.ttf"])
    for n in names:
        try:
            return ImageFont.truetype(n, size * SCALE)
        except OSError:
            continue
    return ImageFont.load_default()


def render_table(title, col_headers, rows, caption, out_path):
    """rows: list of (label, [cell strings]); last column rendered bold/bright."""
    f_title = _font(20, bold=True)
    f_head = _font(14, bold=True)
    f_cell = _font(17)
    f_cell_b = _font(17, bold=True)
    f_cap = _font(15)

    pad = 24 * SCALE
    row_h = 62 * SCALE
    head_h = 56 * SCALE

    tmp = Image.new("RGB", (10, 10))
    d = ImageDraw.Draw(tmp)

    def w_of(text, font):
        return d.textlength(text, font=font)

    label_w = max([w_of("DATASET", f_head)] + [w_of(r[0], f_cell) for r in rows]) + 40 * SCALE
    col_ws = []
    for j, h in enumerate(col_headers):
        cells = [w_of(r[1][j], f_cell_b) for r in rows]
        col_ws.append(max([w_of(h.upper(), f_head)] + cells) + 70 * SCALE)

    card_w = int(label_w + sum(col_ws) + 2 * pad)
    min_w = 900 * SCALE
    if card_w < min_w:
        extra = (min_w - card_w) // len(col_ws)
        col_ws = [w + extra for w in col_ws]
        card_w = int(label_w + sum(col_ws) + 2 * pad)
    card_h = int(head_h + row_h * len(rows))

    margin = 26 * SCALE
    title_h = 58 * SCALE
    cap_lines = _wrap(caption, f_cap, card_w, d) if caption else []
    cap_h = (len(cap_lines) * 24 * SCALE + 18 * SCALE) if cap_lines else 0
    W = card_w + 2 * margin
    H = title_h + card_h + cap_h + 2 * margin

    img = Image.new("RGB", (W, H), BG)
    draw = ImageDraw.Draw(img)

    draw.text((margin, margin), title, font=f_title, fill=BRIGHT_FG)

    cx, cy = margin, margin + title_h
    draw.rounded_rectangle([cx, cy, cx + card_w, cy + card_h], radius=14 * SCALE,
                           fill=CARD, outline=BORDER, width=SCALE)

    # header row
    hy = cy + head_h // 2
    draw.text((cx + pad, hy), "DATASET", font=f_head, fill=HEADER_FG, anchor="lm")
    x = cx + pad + label_w
    for j, h in enumerate(col_headers):
        draw.text((x + col_ws[j] - 10 * SCALE, hy), h.upper(), font=f_head,
                  fill=HEADER_FG, anchor="rm")
        x += col_ws[j]
    draw.line([cx + SCALE, cy + head_h, cx + card_w - SCALE, cy + head_h],
              fill=ROW_LINE, width=SCALE)

    # data rows
    for i, (label, cells) in enumerate(rows):
        ry = cy + head_h + i * row_h
        my = ry + row_h // 2
        draw.text((cx + pad, my), label, font=f_cell, fill=BRIGHT_FG, anchor="lm")
        x = cx + pad + label_w
        for j, cell in enumerate(cells):
            last = (j == len(cells) - 1) and len(cells) > 1
            draw.text((x + col_ws[j] - 10 * SCALE, my), cell,
                      font=(f_cell_b if last else f_cell),
                      fill=(BRIGHT_FG if last else DIM_FG), anchor="rm")
            x += col_ws[j]
        if i < len(rows) - 1:
            draw.line([cx + SCALE, ry + row_h, cx + card_w - SCALE, ry + row_h],
                      fill=ROW_LINE, width=SCALE)

    # caption
    ty = cy + card_h + 18 * SCALE
    for line in cap_lines:
        draw.text((margin, ty), line, font=f_cap, fill=CAPTION_FG)
        ty += 24 * SCALE

    img = img.resize((W // SCALE, H // SCALE), Image.LANCZOS)
    img.save(out_path)
    print(f"wrote {out_path}")


def _wrap(text, font, max_w, d):
    words, lines, cur = text.split(), [], ""
    for w in words:
        t = (cur + " " + w).strip()
        if d.textlength(t, font=font) > max_w:
            lines.append(cur)
            cur = w
        else:
            cur = t
    if cur:
        lines.append(cur)
    return lines


# ---- result-file handling ----

def load_runs(paths):
    return [json.load(open(p, encoding="utf-8")) for p in paths]


def render_runs(runs, out_path=None):
    """One run -> per-model metrics table. Multiple runs -> model-comparison table."""
    datasets = []
    for run in runs:
        for ds in run["datasets"]:
            if ds not in datasets:
                datasets.append(ds)

    # comparison metric priority: accuracy when every run was scored, else
    # acceptance length when every run has it, else tok/s — never mix units
    scored = all(run.get("scored") for run in runs)
    spec = all(run.get("speculative") for run in runs)
    metric_key = "accuracy" if scored else "accept_len" if spec else "tok_s"

    if len(runs) == 1:
        run = runs[0]
        cols = (["Accept. len", "Accept. rate", "Tok/s"] if run.get("speculative")
                else ["Tok/s", "TTFT (s)", "Tokens"])
        if run.get("scored"):
            cols = ["Tok/s", "Score"]
        rows = []
        for ds in datasets:
            m = run["results"][ds]
            if run.get("scored"):
                rows.append((ds, [f"{m['tok_s']:.1f}", _score_cell(m)]))
            elif run.get("speculative"):
                al = f"{m['accept_len']:.2f}" if "accept_len" in m else "—"
                ar = f"{m['accept_rate']*100:.1f}%" if "accept_rate" in m else "—"
                rows.append((ds, [al, ar, f"{m['tok_s']:.1f}"]))
            else:
                rows.append((ds, [f"{m['tok_s']:.2f}", f"{m['ttft']:.2f}",
                                  f"{m['tokens']:.0f}"]))
        if run.get("scored"):
            rows.append((_mean_label(run), [_mean_cell(run, datasets, "tok_s"),
                                            _composite_cell(run, datasets)]))
        else:
            keys = (["accept_len", "accept_rate", "tok_s"] if run.get("speculative")
                    else ["tok_s", "ttft", "tokens"])
            rows.append(("Mean", [_mean_cell(run, datasets, k) for k in keys]))
        title = run["model_label"]
        caption = _caption(run)
        out = out_path or os.path.join(HERE, "results", _slug(title) + ".png")
    else:
        cols = [r["model_label"] for r in runs]
        rows = []
        for ds in datasets:
            cells = []
            for r in runs:
                m = r["results"].get(ds)
                if not m:
                    cells.append("—")
                elif scored:
                    cells.append(_score_cell(m, with_n=False))
                else:
                    v = m.get(metric_key)
                    cells.append("—" if v is None else f"{v:.2f}")
            rows.append((ds, cells))
        if scored:
            rows.append((_mean_label(*runs),
                         [_composite_cell(r, datasets) for r in runs]))
        else:
            rows.append(("Mean", [_mean_cell(r, datasets, metric_key) for r in runs]))
        title = ("Benchmark score (0-100)" if scored else
                 "Mean acceptance length" if spec else "Tokens per second")
        caption = _caption(runs[0], multi=True)
        out = out_path or os.path.join(HERE, "results", "comparison.png")

    render_table(title, cols, rows, caption, out)


# scorers whose 0-100 number is a pass rate and reads correctly as a percentage;
# None covers result files written before per-dataset scorers were recorded
PCT_SCORERS = (None, "exact match", "execution pass@1")


def _score_cell(m, with_n=True):
    """One scored cell. A pass rate keeps its % sign; a continuous scorer
    (ROUGE-L, judge rubric) shows the plain 0-100 index it actually is."""
    if "accuracy" not in m:
        return "—"
    score = m.get("score", m["accuracy"] * 100)
    cell = f"{score:.0f}%" if m.get("scorer") in PCT_SCORERS else f"{score:.1f}"
    if with_n and "graded_n" in m:
        tr = f", {m['truncated_n']} trunc" if m.get("truncated_n") else ""
        cell += f" ({m['graded_n']}{tr})"
    return cell


def _mean_label(*runs):
    """METHODOLOGY rule 21: the Mean is a composite index, never an accuracy —
    say so in the row label whenever the run recorded one."""
    return "Mean (composite)" if any(r.get("composite") for r in runs) else "Mean"


def _composite_cell(run, datasets):
    """The composite index over this run's *scored* benchmarks. Falls back to
    the plain accuracy mean for result files written before rule 21."""
    comp = run.get("composite")
    if comp and comp.get("mean") is not None:
        return f"{comp['mean']:.1f}"
    return _mean_cell(run, datasets, "accuracy")


def _mean_cell(run, datasets, key):
    cells = [run["results"][ds] for ds in datasets if ds in run["results"]]
    vals = [m[key] for m in cells if key in m]
    if not vals:
        return "—"
    v = sum(vals) / len(vals)
    if key == "accuracy":
        return f"{v*100:.0f}%"
    if key == "accept_rate":
        return f"{v*100:.1f}%"
    if key == "tokens":
        return f"{v:.0f}"
    if key == "ttft":
        return f"{v:.2f}"
    return f"{v:.2f}"


def _caption(run, multi=False):
    s = run["settings"]
    what = ("Benchmark scores" if run.get("scored")
            else "Per-request mean acceptance length" if run.get("speculative")
            else "Generation throughput")
    draft = f", draft model {run['draft_model']}" if run.get("draft_model") else ""
    seed = f", seed {s['seed']}" if "seed" in s else ""
    mach = run.get("machine", {})
    where = mach.get("gpu") or mach.get("cpu") or ""
    where = f" on {mach['host']} ({where})" if mach.get("host") else ""
    suite = f", suite {run['suite_hash']}" if run.get("suite_hash") else ""
    backend = run.get("backend", {})
    engine = backend.get("engine", "llama.cpp via LM Studio's server")
    sa = backend.get("server_args")
    sa = f" [{sa}]" if sa else ""
    ctx = f" -c {backend['ctx']}" if backend.get("ctx") else ""
    protocol = f" {run['protocol']}." if run.get("protocol") else ""
    return (f"{what}. Sampling: temperature {s['temperature']}, top-p {s['top_p']}, "
            f"top-k {s['top_k']}, presence penalty {s['presence_penalty']}{seed}, "
            f"{s['samples']} samples/dataset, max {s['max_tokens']} tokens{draft}{suite}. "
            f"Engine: {engine}{sa}{ctx}{where}.{protocol}{_scoring_note(run)}")


def _scoring_note(run):
    """Rule 21's labeling duty: what the Mean is, which benchmarks it left out,
    and who did any judging."""
    parts = []
    comp = run.get("composite")
    if comp:
        parts.append(f" Mean is the {comp['label']}: each scored benchmark "
                     f"normalized to 0-100 by its own scorer, then averaged "
                     f"— not an accuracy.")
        if comp.get("excluded"):
            parts.append(" Excluded: " + "; ".join(
                f"{d} ({why})" for d, why in comp["excluded"].items()) + ".")
    scorers = run.get("scorers") or {}
    if scorers:
        parts.append(" Scorers: " + ", ".join(
            f"{d} {how}" for d, how in scorers.items()) + ".")
    j = run.get("judge")
    if j:
        flag = " [SELF-JUDGE — not an independent score]" if j.get("self_judge") else ""
        parts.append(f" Judge: {j['model']} at {j['url']}{flag}.")
    return "".join(parts)


def _slug(s):
    return "".join(c if c.isalnum() or c in "-_" else "_" for c in s)


if __name__ == "__main__":
    args = sys.argv[1:]
    if not args or args[0] == "--latest":
        files = sorted(glob.glob(os.path.join(HERE, "results", "*.json")),
                       key=os.path.getmtime)
        if not files:
            sys.exit("no result files in results/")
        args = files[-1:] if (not args or args[0] == "--latest") else args
    render_runs(load_runs(args))
