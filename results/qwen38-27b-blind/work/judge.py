"""Static compliance checker for the aquarium effort task.

Mechanical evidence only. It reports what each candidate file DOES and DOES NOT
contain against the numbered requirements in templates/effort-task-example.md;
the /100 score is assigned by a human/agent reading this evidence, not by this
script. Run:  python judge.py <file.html> [...]
"""
import re, sys, json, os

REQ_CONFIG = {
    "fish count per species": r"(FISH|TROPICAL|ANGEL|SCHOOL)\w*(COUNT|_N\b|NUM)",
    "speed multiplier":       r"SPEED\w*(MULT|MULTIPLIER|SCALE)|GLOBAL_SPEED|SPEED_MULT",
    "bubble spawn interval":  r"BUBBLE\w*(INTERVAL|SPAWN|RATE|MS)",
    "jellyfish count":        r"JELLY\w*(COUNT|NUM|_N\b)",
    "crab count":             r"CRAB\w*(COUNT|NUM|_N\b)",
    "max simultaneous bubbles": r"(MAX\w*BUBBL|BUBBL\w*MAX)",
    "day/night cycle duration": r"(DAY\w*NIGHT|NIGHT\w*DAY|CYCLE\w*(SEC|DUR))",
}

CREATURES = {
    "tropical fish":  r"tropical",
    "angelfish":      r"angel",
    "schooling fish": r"school",
    "jellyfish":      r"jelly",
    "crab":           r"\bcrab",
    "lobster":        r"lobster",
    "starfish":       r"starfish|sea ?star",
    "seahorse":       r"seahorse|sea ?horse",
    "sea turtle":     r"turtle",
}
SCENERY = {
    "conch/spiral shell": r"conch|spiral",
    "scallop/fan shell":  r"scallop|\bfan\b",
    "cowrie shell":       r"cowrie|cowry",
    "coral":              r"coral",
    "anemone":            r"anemone",
    "seaweed/kelp":       r"kelp|seaweed",
    "rocks":              r"\brock",
    "bubbles":            r"bubble",
    "caustic rays":       r"caustic|light ?ray|godray|god ?ray|sunbeam|shaft",
    "sandy floor":        r"sand",
    "particle motes":     r"\bmote|particle|speck",
    "day/night":          r"day.?night|nightFactor|dayNight",
}
QUALITY = {
    "requestAnimationFrame": r"requestAnimationFrame",
    "delta time":            r"\b(dt|delta|deltaTime|elapsed)\b",
    "resize handling":       r"(addEventListener\(\s*['\"]resize|onresize|ResizeObserver)",
    "devicePixelRatio":      r"devicePixelRatio",
    "canvas 2d context":     r"getContext\(\s*['\"]2d",
}
EXTERNAL = {
    "http(s) URL":   r"https?://",
    "<link rel>":    r"<link\b",
    "<script src>":  r"<script[^>]+\bsrc\s*=",
    "<img src>":     r"<img\b",
    "@import":       r"@import",
    "fetch()":       r"\bfetch\s*\(",
    "XMLHttpRequest": r"XMLHttpRequest",
}

def analyse(path):
    src = open(path, encoding="utf-8", errors="replace").read()
    low = src.lower()
    out = {"file": os.path.basename(path), "bytes": len(src),
           "lines": src.count("\n") + 1}
    out["has_doctype"] = bool(re.match(r"\s*<!doctype html", low))
    out["has_html_close"] = "</html>" in low
    out["canvas_tags"] = len(re.findall(r"<canvas\b", low))
    # CONFIG object
    m = re.search(r"(const|let|var)\s+CONFIG\s*=\s*\{", src)
    out["config_object"] = bool(m)
    cfg_body = ""
    if m:
        i = src.index("{", m.start()); depth = 0
        for j in range(i, len(src)):
            if src[j] == "{": depth += 1
            elif src[j] == "}":
                depth -= 1
                if depth == 0: cfg_body = src[i:j+1]; break
    out["config_chars"] = len(cfg_body)
    out["config_keys"] = len(re.findall(r"^\s*[A-Za-z_$][\w$]*\s*:", cfg_body, re.M))
    out["config_required"] = {k: bool(re.search(p, cfg_body, re.I))
                              for k, p in REQ_CONFIG.items()}
    out["creatures"] = {k: len(re.findall(p, low)) for k, p in CREATURES.items()}
    out["scenery"] = {k: len(re.findall(p, low)) for k, p in SCENERY.items()}
    out["quality"] = {k: bool(re.search(p, src)) for k, p in QUALITY.items()}
    ext = {}
    for k, p in EXTERNAL.items():
        hits = re.findall(p, src, re.I)
        if k == "http(s) URL":
            hits = [h for h in re.findall(r"https?://[^\s\"'<>)]+", src)
                    if "w3.org" not in h]      # xmlns is not a network request
        if hits: ext[k] = len(hits)
    out["external_refs"] = ext
    out["draw_functions"] = sorted(set(re.findall(r"function\s+(draw\w+)", src)) |
                                   set(re.findall(r"(draw\w+)\s*[:=]\s*(?:function|\()", src)))
    out["classes"] = sorted(set(re.findall(r"class\s+([A-Z]\w+)", src)))
    # numeric literals that look like counts in CONFIG
    out["config_preview"] = cfg_body[:1400]
    return out

if __name__ == "__main__":
    res = [analyse(p) for p in sys.argv[1:]]
    print(json.dumps(res, indent=1))
