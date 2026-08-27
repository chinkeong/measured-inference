"""Phase 10 - integrate the 1 Hz power log over each recorded generation window.
kWh = mean_load_watts * wall_seconds / 3.6e6. Gross draw, idle NOT subtracted.
(The PowerShell version tripped over Windows PowerShell 5.1's TryParseExact
overload resolution; this is the version whose numbers the report uses.)"""
import datetime, os, re, sys
DATA = r"E:\AI\measured-inference\results\qwen38-27b-blind\data"

def load(csv):
    rows = []
    for line in open(csv, encoding="utf-8", errors="replace"):
        p = [x.strip() for x in line.split(",")]
        if len(p) < 2:
            continue
        try:
            t = datetime.datetime.strptime(p[0], "%Y/%m/%d %H:%M:%S.%f")
            w = float(p[1].replace(" W", ""))
        except Exception:
            continue
        rows.append((t, w))
    return rows

rows = load(os.path.join(DATA, "power.csv"))
out = []
out.append("SAMPLES n=%d span=%s..%s" % (len(rows), rows[0][0], rows[-1][0]))
out.append("NOTE gross GPU draw, idle NOT subtracted. Cold board idle with no "
           "server loaded measured 33.2 W at campaign start; the first samples "
           "of this log read ~58 W because the GPU was still cooling.")
txt = open(os.path.join(DATA, "phase7.txt"), encoding="utf-8").read()
for m in re.finditer(r"RESULT effort-(\w+) .*?predicted_n=(\d+).*?"
                     r"t0=\[(.+?)\] t1=\[(.+?)\]", txt):
    lvl, tok, a, b = m.group(1), int(m.group(2)), m.group(3), m.group(4)
    t0 = datetime.datetime.strptime(a, "%Y/%m/%d %H:%M:%S")
    t1 = datetime.datetime.strptime(b, "%Y/%m/%d %H:%M:%S")
    ws = [w for t, w in rows if t0 <= t <= t1]
    if not ws:
        out.append("ENERGY %s NO-SAMPLES" % lvl); continue
    secs = (t1 - t0).total_seconds()
    mean = sum(ws) / len(ws)
    kwh = mean * secs / 3.6e6
    out.append("ENERGY %-7s n=%d wall_s=%.0f mean_W=%.1f peak_W=%.1f "
               "Wh_per_answer=%.2f kWh_per_answer=%.6f tokens=%d "
               "Wh_per_1k_tok=%.3f" % (lvl, len(ws), secs, mean, max(ws),
                                       kwh * 1000, kwh, tok,
                                       kwh / max(tok, 1) * 1e6))
print("\n".join(out))
open(os.path.join(DATA, "phase10.txt"), "w", encoding="utf-8").write(
    "\n".join(out) + "\n")
