#!/usr/bin/env python3
"""Where does this model stop being able to READ an image?

The first 6c pass answered a question it did not mean to ask. Arm A sent the
1024x1024 nonce, got no digits back, and recorded FAIL-blind -- but the same
run's resolution map had already shown the SAME nonce read correctly at
1920x1080 and 3840x2160. The model is not blind at 1024; it is below its text
acuity there. Arm A measured my choice of resolution, not the model.

The interesting quantity is therefore not pass/fail but the THRESHOLD, and it is
directly actionable: it tells a reader the minimum resolution at which a
screenshot fed to this model can be trusted to be read rather than guessed at.

Two things make this a measurement rather than an anecdote:
  - the SAME nonce at every rung, so only resolution moves;
  - THREE repeats per rung, because a single miss at a boundary rung is noise
    and this is exactly the region where the answer will be unstable.

The failure mode matters as much as the threshold. At 768 the model answered
"202014" and at 1024 it described the text as "20204" and "creation" -- the
true content is "686954" and "crimson". That is not blindness and it is not
refusal: it is CONFIDENT MISREADING, which is the shape rule 19 cares about,
because a reader cannot tell it from a correct answer without the ground truth.
"""
import json, os, subprocess, sys, time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
REPO = os.path.abspath(os.path.join(HERE, "..", "..", ".."))
sys.path.insert(0, os.path.join(REPO, "scripts", "lib"))
sys.path.insert(0, os.path.join(REPO, "scripts", "bench"))
import paths, gpu_lock                                          # noqa: E402
sys.path.insert(0, HERE)
import importlib.util                                           # noqa: E402
spec = importlib.util.spec_from_file_location(
    "v6c", os.path.join(HERE, "stage6c-vision.py"))
v6c = importlib.util.module_from_spec(spec)
sys.modules["v6c"] = v6c
spec.loader.exec_module.__self__ if False else None
import types                                                    # noqa: E402
# import without running main()
src = open(os.path.join(HERE, "stage6c-vision.py")).read().split('if __name__')[0]
exec(compile(src, "stage6c-vision.py", "exec"), v6c.__dict__)

RUNGS = [(768, 768), (1024, 1024), (1280, 720), (1280, 1280), (1536, 864),
         (1600, 900), (1920, 1080)]
REPS = 3
OUT = os.path.join(REPO, "results", "ornith-1.5-9b-mtp", "data", "vision-acuity.json")


def main():
    digits, colour = "686954", "crimson"     # the same nonce as the 6c pass
    out = {"_schema": "vision-acuity v1",
           "question": "at what resolution can this model READ 6-digit text?",
           "nonce": {"digits": digits, "colour": colour},
           "reps": REPS, "rungs": []}
    os.makedirs(v6c.SHOTS, exist_ok=True)
    gpu_lock.acquire("stage6c-acuity")
    cmd = [v6c.SERVER, "-m", v6c.MODEL, "--mmproj", v6c.MMPROJ, "-c", "32768",
           "-ngl", "99", "--parallel", "1", "--jinja", "--host", "127.0.0.1",
           "--port", str(v6c.PORT)]
    logf = open(os.path.join(v6c.WORK, "stage6c-acuity-server.log"), "w")
    p = gpu_lock.serve(cmd, tag="acuity", stdout=logf, stderr=subprocess.STDOUT)
    try:
        import urllib.request
        for _ in range(300):
            try:
                urllib.request.urlopen("http://127.0.0.1:%d/health" % v6c.PORT, timeout=3); break
            except Exception:
                time.sleep(2)
        Q = ("What six-digit number is written in this image? "
             "Reply with the six digits only, nothing else.")
        for (w, h) in RUNGS:
            path = os.path.join(v6c.SHOTS, "acuity-%dx%d.png" % (w, h))
            v6c.make_nonce_image(path, w, h, digits, colour)
            hits, answers, toks = 0, [], None
            for _ in range(REPS):
                a = v6c.ask(Q, path, 64)
                toks = a["usage"].get("prompt_tokens")
                ok = digits in a["full"]
                hits += 1 if ok else 0
                # what it said instead -- the misread is the finding
                seen = "".join(ch for ch in a["full"] if ch.isdigit())[:24]
                answers.append({"correct": ok, "digits_seen": seen,
                                "reply": (a["text"] or "").strip()[:40]})
            row = {"w": w, "h": h, "pixels": w * h, "prompt_tokens": toks,
                   "hits": hits, "of": REPS, "answers": answers}
            out["rungs"].append(row)
            print("[%s] %-11s px=%-8d tok=%-5s %d/%d correct   saw %s" % (
                time.strftime("%H:%M:%S"), "%dx%d" % (w, h), w * h, toks,
                hits, REPS, [x["digits_seen"][:10] for x in answers]), flush=True)
            json.dump(out, open(OUT, "w"), indent=1)
    finally:
        try:
            p.terminate(); p.wait(timeout=30)
        except Exception:
            try: p.kill()
            except Exception: pass
        logf.close()
    json.dump(out, open(OUT, "w"), indent=1)
    print("wrote %s" % OUT, flush=True)


if __name__ == "__main__":
    main()
