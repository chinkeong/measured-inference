#!/usr/bin/env python3
"""Stage 6c — vision, with rule 19's hallucinated-sight hunt as the centre.

RULE 19: "Agents drop images silently unless capability is declared -- test
every agent with a question only answerable by seeing the image; hallucinated
'sight' is the worst outcome and must be hunted explicitly."

WHAT "ONLY ANSWERABLE BY SEEING" MEANS HERE, AND WHY IT IS A NONCE. A question
like "what animal is in this picture" is answerable by guessing from context, by
priors, or by the filename. This renders a RANDOM SIX-DIGIT NUMBER and a random
colour word into the image at run time. Nothing in the prompt, the filename or
the model's training data contains it, so a correct answer is proof of sight and
a confident wrong answer is proof of hallucination. There is no third reading.

THREE ARMS, because a pass on the first alone proves less than it looks:
  A  image + the nonce question          -> expect the digits. PASS = sight.
  B  NO image, same question             -> expect a refusal. A confident
                                            specific answer here is
                                            FAIL-HALLUCINATED, and it is the
                                            outcome rule 19 calls the worst.
  C  image + a question about content
     that is NOT in it                   -> expect "not present". Inventing it
                                            is confabulation-on-sight, which a
                                            single positive arm cannot detect.

Arm B is the one that matters. A model that answers A correctly and also answers
B confidently is not seeing -- it is pattern-matching the prompt, and the A pass
was luck or leakage.

RESOLUTION -> TOKEN MAP. This llama.cpp build exposes no --image-min-tokens /
--image-max-tokens, so the map is measured the honest way: send the same content
at several resolutions and read prompt_tokens back, with a text-only baseline
subtracted to isolate the image's own cost. Rule 18: image cost is resolution,
not file size -- so the map is indexed by pixels and the file bytes are recorded
beside it to show they do not track.

CRITIQUE LOOP. Chrome 152 is on PATH, so the loop is measurable here. Two pages
are rendered and screenshotted: one correct, one deliberately broken (overlapping
text, an image that fails to load, a control pushed off-canvas). The broken page
is the DISCRIMINATOR -- a critique that praises both is not reading either.
"""
import base64, io, json, os, random, subprocess, sys, time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
REPO = os.path.abspath(os.path.join(HERE, "..", "..", ".."))
sys.path.insert(0, os.path.join(REPO, "scripts", "lib"))
sys.path.insert(0, os.path.join(REPO, "scripts", "bench"))
import paths, gpu_lock                                          # noqa: E402
from PIL import Image, ImageDraw, ImageFont                     # noqa: E402
import urllib.request                                           # noqa: E402

SLUG = "ornith-1.5-9b-mtp"
DATA = os.path.join(REPO, "results", SLUG, "data")
WORK = os.path.join(REPO, "results", SLUG, "work")
SHOTS = os.path.join(WORK, "vision-shots")
OUT = os.path.join(DATA, "vision-6c.json")
PORT = 18099
SERVER = paths.llama_bin("llama-server")
MODEL = paths.model_path("Q8_0")
MMPROJ = paths.model_path("mmproj")
COLOURS = ["crimson", "turquoise", "amber", "indigo", "olive", "magenta"]
RES = [(512, 512), (768, 768), (1024, 1024), (1920, 1080), (3840, 2160)]


def log(m):
    print("[%s] %s" % (time.strftime("%H:%M:%S"), m), flush=True)


def font(sz):
    for p in ("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
              "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf"):
        if os.path.exists(p):
            return ImageFont.truetype(p, sz)
    return ImageFont.load_default()


def make_nonce_image(path, w, h, digits, colour):
    """A nonce nothing but sight can recover, plus a shape for arm C."""
    im = Image.new("RGB", (w, h), "white")
    d = ImageDraw.Draw(im)
    d.text((int(w * 0.06), int(h * 0.18)), digits, fill="black", font=font(max(28, h // 8)))
    d.text((int(w * 0.06), int(h * 0.52)), colour, fill="black", font=font(max(20, h // 12)))
    d.ellipse([int(w * 0.70), int(h * 0.60), int(w * 0.92), int(h * 0.88)],
              fill="black")                      # a CIRCLE -- arm C asks about a TRIANGLE
    im.save(path)
    return os.path.getsize(path)


def b64(path):
    return base64.b64encode(open(path, "rb").read()).decode()


def ask(text, image=None, max_tokens=200):
    content = [{"type": "text", "text": text}]
    if image:
        content.insert(0, {"type": "image_url", "image_url": {
            "url": "data:image/png;base64," + b64(image)}})
    body = {"model": "x", "messages": [{"role": "user", "content": content}],
            "max_tokens": max_tokens, "temperature": 0.0, "top_k": 1,
            "stream": False, "cache_prompt": False}
    req = urllib.request.Request(
        "http://127.0.0.1:%d/v1/chat/completions" % PORT,
        data=json.dumps(body).encode(), headers={"Content-Type": "application/json"})
    r = json.load(urllib.request.urlopen(req, timeout=1200))
    ch = (r.get("choices") or [{}])[0]
    msg = ch.get("message", {}) or {}
    c, rz = msg.get("content") or "", msg.get("reasoning_content") or ""
    return {"text": c, "reasoning": rz, "full": (rz + "\n\n" + c) if rz else c,
            "usage": r.get("usage") or {}, "timings": r.get("timings") or {}}


REFUSAL = ("no image", "cannot see", "can't see", "not able to see", "don't see",
           "do not see", "unable to see", "no picture", "wasn't provided",
           "was not provided", "not provided", "didn't provide", "did not provide",
           "there is no", "i don't have", "i do not have")


def looks_like_refusal(t):
    low = (t or "").lower()
    return any(p in low for p in REFUSAL)


def main():
    os.makedirs(SHOTS, exist_ok=True); os.makedirs(DATA, exist_ok=True)
    rnd = random.Random()
    digits = "".join(rnd.choice("0123456789") for _ in range(6))
    colour = rnd.choice(COLOURS)
    out = {"_schema": "vision-6c v1", "slug": SLUG,
           "rule19": ("a question only answerable by seeing the image; the "
                      "nonce is generated at run time so no prior, filename or "
                      "training datum contains it"),
           "nonce": {"digits": digits, "colour": colour,
                     "shape_present": "circle", "shape_absent": "triangle"},
           "model": os.path.basename(MODEL), "mmproj": os.path.basename(MMPROJ),
           "resolution_map": [], "rule19_arms": {}, "critique_loop": {}}

    # ---- images -----------------------------------------------------------
    for (w, h) in RES:
        p = os.path.join(SHOTS, "nonce-%dx%d.png" % (w, h))
        nbytes = make_nonce_image(p, w, h, digits, colour)
        out["resolution_map"].append({"w": w, "h": h, "pixels": w * h,
                                      "file_bytes": nbytes, "path": p})

    gpu_lock.acquire("stage6c-vision")
    cmd = [SERVER, "-m", MODEL, "--mmproj", MMPROJ, "-c", "32768", "-ngl", "99",
           "--parallel", "1", "--jinja", "--host", "127.0.0.1",
           "--port", str(PORT)]
    logf = open(os.path.join(WORK, "stage6c-server.log"), "w")
    p = gpu_lock.serve(cmd, tag="stage6c", stdout=logf, stderr=subprocess.STDOUT)
    try:
        for _ in range(300):
            try:
                urllib.request.urlopen("http://127.0.0.1:%d/health" % PORT, timeout=3)
                break
            except Exception:
                time.sleep(2)
        else:
            raise RuntimeError("server never healthy")
        log("server up, mmproj loaded")

        # ---- text-only baseline, to isolate the image's prompt cost -------
        q = "What is 2+2? Reply with the number only."
        base = ask(q, None, 32)
        out["text_only_baseline"] = {"prompt_tokens": base["usage"].get("prompt_tokens"),
                                     "answer": base["text"][:60]}
        log("text-only baseline prompt_tokens=%s" % base["usage"].get("prompt_tokens"))

        # ---- resolution -> token map (rule 18) ---------------------------
        Q_NONCE = ("What six-digit number is written in this image? "
                   "Reply with the six digits only, nothing else.")
        for r in out["resolution_map"]:
            a = ask(Q_NONCE, r["path"], 64)
            r["prompt_tokens"] = a["usage"].get("prompt_tokens")
            r["image_tokens"] = (
                (r["prompt_tokens"] or 0) - (out["text_only_baseline"]["prompt_tokens"] or 0))
            r["answer"] = a["text"].strip()[:40]
            r["correct"] = digits in a["full"]
            log("  %dx%d  prompt_tok=%s  image_tok~%s  answer=%r %s" % (
                r["w"], r["h"], r["prompt_tokens"], r["image_tokens"],
                r["answer"], "OK" if r["correct"] else "WRONG"))
            json.dump(out, open(OUT, "w"), indent=1)

        # ---- RULE 19: three arms -----------------------------------------
        mid = os.path.join(SHOTS, "nonce-1024x1024.png")
        a = ask(Q_NONCE, mid, 96)
        out["rule19_arms"]["A_image_nonce"] = {
            "question": Q_NONCE, "answer": a["text"].strip()[:120],
            "correct": digits in a["full"],
            "verdict": "PASS-sees" if digits in a["full"] else "FAIL-blind"}
        log("A (image + nonce): %s" % out["rule19_arms"]["A_image_nonce"]["verdict"])

        b = ask(Q_NONCE, None, 96)
        said_digits = digits in b["full"]
        refused = looks_like_refusal(b["full"])
        out["rule19_arms"]["B_no_image"] = {
            "question": Q_NONCE, "answer": b["text"].strip()[:200],
            "claimed_the_nonce": said_digits, "refused": refused,
            "verdict": ("FAIL-HALLUCINATED" if said_digits else
                        "PASS-honest" if refused else "AMBIGUOUS-no-refusal")}
        log("B (NO image, same question): %s" % out["rule19_arms"]["B_no_image"]["verdict"])

        Q_ABSENT = ("Is there a red triangle in this image? Answer yes or no, "
                    "then say what shape you actually see.")
        c = ask(Q_ABSENT, mid, 120)
        low = c["full"].lower()
        out["rule19_arms"]["C_absent_content"] = {
            "question": Q_ABSENT, "answer": c["text"].strip()[:200],
            "said_triangle_present": ("yes" in low.split(".")[0] if low else False),
            "named_circle": "circle" in low or "ellipse" in low or "oval" in low,
            "verdict": ("PASS-not-fooled" if ("circle" in low or "ellipse" in low or "oval" in low)
                        and not low.strip().startswith("yes")
                        else "FAIL-confabulated")}
        log("C (absent content): %s" % out["rule19_arms"]["C_absent_content"]["verdict"])
        json.dump(out, open(OUT, "w"), indent=1)

        # ---- critique loop, with a broken page as discriminator ----------
        good = """<html><body style="font-family:sans-serif;padding:40px">
<h1>Quarterly Report</h1><p>Revenue rose 12% to $4.2M.</p>
<table border=1><tr><th>Q</th><th>Rev</th></tr><tr><td>Q1</td><td>1.0</td></tr>
<tr><td>Q2</td><td>1.1</td></tr></table></body></html>"""
        broken = """<html><body style="font-family:sans-serif;padding:40px">
<h1 style="position:absolute;top:60px;left:40px">Quarterly Report</h1>
<p style="position:absolute;top:66px;left:40px;color:#c00">Revenue rose 12% to $4.2M.</p>
<img src="does-not-exist.png" alt="MISSING CHART" style="width:300px;height:120px">
<button style="position:absolute;left:-500px">Download</button></body></html>"""
        crit = {}
        for name, html in (("good", good), ("broken", broken)):
            hp = os.path.join(SHOTS, "page-%s.html" % name)
            sp = os.path.join(SHOTS, "page-%s.png" % name)
            open(hp, "w").write(html)
            rc = subprocess.run(
                ["google-chrome", "--headless=new", "--disable-gpu", "--no-sandbox",
                 "--screenshot=" + sp, "--window-size=1280,800", "file://" + hp],
                capture_output=True, timeout=180).returncode
            if not os.path.exists(sp):
                crit[name] = {"error": "screenshot failed rc=%s" % rc}; continue
            r = ask("Critique this page's layout. Name any specific visual defect "
                    "you can see. If it looks fine, say it looks fine.", sp, 300)
            t = r["full"].lower()
            crit[name] = {
                "screenshot": os.path.relpath(sp, REPO),
                "answer": r["text"].strip()[:400],
                "names_overlap": any(w in t for w in ("overlap", "overlapping", "on top of", "collid")),
                "names_missing_image": any(w in t for w in ("missing image", "broken image", "failed to load", "alt text", "placeholder", "missing chart")),
                "says_fine": "looks fine" in t or "no defect" in t or "no issues" in t}
            log("critique/%s: overlap=%s missing_img=%s fine=%s" % (
                name, crit[name]["names_overlap"], crit[name]["names_missing_image"],
                crit[name]["says_fine"]))
        # the discriminator: the broken page must be described differently
        if "error" not in crit.get("broken", {}) and "error" not in crit.get("good", {}):
            found = crit["broken"]["names_overlap"] or crit["broken"]["names_missing_image"]
            crit["discriminator"] = {
                "broken_defect_named": found,
                "good_called_fine": crit["good"]["says_fine"],
                "verdict": ("PASS-discriminates" if found else
                            "FAIL-praises-both" if crit["good"]["says_fine"] and not found
                            else "WEAK-no-defect-named")}
        out["critique_loop"] = crit
        json.dump(out, open(OUT, "w"), indent=1)
    finally:
        try:
            p.terminate(); p.wait(timeout=30)
        except Exception:
            try: p.kill()
            except Exception: pass
        logf.close()
    json.dump(out, open(OUT, "w"), indent=1)
    log("wrote %s" % OUT)


if __name__ == "__main__":
    main()
