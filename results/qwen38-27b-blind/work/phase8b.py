"""Phase 8b - vision: resolution -> token cost, measured properly.

The PowerShell attempt failed: Invoke-RestMethod on Windows PowerShell 5.1
cannot post the ~261 KB body a 1440p PNG data-URI produces, and the request
never reached the server at all (the server log shows no task). Redone in
Python, where the same request succeeds in under four seconds.

Arms:
  vis-default : no image-token flags   -> the model's own resize policy
  vis-min1024 : --image-min-tokens 1024 -> the floor llama.cpp warns Qwen-VL
                needs for grounding
Each arm sends a text-only baseline (to subtract), then a 720p and a 1440p
screenshot of a real local HTML page.
"""
import base64, json, os, subprocess, sys, time, urllib.request

DATA = r"E:\AI\measured-inference\results\qwen38-27b-blind\data"
EXE = r"E:\AI\llama.cpp\llama-server.exe"
MODEL = r"C:\Users\chink\.lmstudio\models\unsloth\Qwen3.8-27B-GGUF\Qwen3.8-27B-UD-IQ4_XS.gguf"
MMPROJ = r"C:\Users\chink\.lmstudio\models\lmstudio-community\Qwen3.8-27B-GGUF\mmproj-Qwen3.8-27B-BF16.gguf"
PORT = 1235
BASE = f"http://127.0.0.1:{PORT}"
ALIAS = "qwen/qwen3.8-27b"
OUT = os.path.join(DATA, "phase8b.txt")

Q = ("Describe this screenshot in two sentences: what kind of page is it, "
     "and name three distinct things visible in it.")


def log(line):
    print(line, flush=True)
    with open(OUT, "a", encoding="utf-8") as f:
        f.write(line + "\n")


def kill_server():
    subprocess.run(["taskkill", "/F", "/IM", "llama-server.exe"],
                   capture_output=True)
    time.sleep(3)


def board_mib():
    try:
        r = subprocess.run(["nvidia-smi", "--query-gpu=memory.used",
                            "--format=csv,noheader,nounits"],
                           capture_output=True, text=True, timeout=15)
        return int(r.stdout.strip().splitlines()[0])
    except Exception:
        return -1


def start_server(extra, tag):
    kill_server()
    err = open(os.path.join(DATA, f"srv-py-{tag}.err.log"), "wb")
    args = [EXE, "-m", MODEL, "--alias", ALIAS, "--host", "127.0.0.1",
            "--port", str(PORT), "--jinja", "--mmproj", MMPROJ] + extra
    p = subprocess.Popen(args, stdout=subprocess.DEVNULL, stderr=err)
    t0 = time.time()
    while time.time() - t0 < 600:
        time.sleep(2)
        try:
            with urllib.request.urlopen(f"{BASE}/health", timeout=3) as r:
                if json.loads(r.read()).get("status") == "ok":
                    log(f"  [{tag}] healthy in {time.time()-t0:.1f}s")
                    return p
        except Exception:
            pass
        if p.poll() is not None:
            log(f"  [{tag}] SERVER EXITED code={p.returncode}")
            return None
    log(f"  [{tag}] SERVER TIMEOUT")
    return None


def chat(content, max_tokens):
    body = {"model": ALIAS, "temperature": 0, "top_k": 1,
            "max_tokens": max_tokens,
            "messages": [{"role": "user", "content": content}]}
    raw = json.dumps(body).encode()
    req = urllib.request.Request(f"{BASE}/v1/chat/completions", data=raw,
                                 headers={"Content-Type": "application/json"})
    t0 = time.time()
    with urllib.request.urlopen(req, timeout=900) as r:
        d = json.loads(r.read())
    d["_wall"] = round(time.time() - t0, 2)
    d["_payload"] = len(raw)
    return d


def data_uri(path):
    return "data:image/png;base64," + base64.b64encode(
        open(path, "rb").read()).decode()


def main():
    shot1440 = os.path.join(DATA, "shot-1440p.png")
    shot720 = os.path.join(DATA, "shot-720p.png")
    if not os.path.exists(shot1440):
        log("PHASE8B: no 1440p screenshot on disk"); return 1
    arms = [("vis-default", []),
            ("vis-min1024", ["--image-min-tokens", "1024"])]
    common = ["-c", "65536", "-ngl", "99", "--parallel", "1",
              "--load-mode", "mmap", "-ctk", "q8_0", "-ctv", "q8_0",
              "--spec-type", "draft-mtp", "--spec-draft-n-max", "4",
              "--spec-draft-p-min", "0.75"]
    for tag, extra in arms:
        log(f"=== {tag} ===")
        p = start_server(common + extra, tag)
        if p is None:
            log(f"RESULT {tag} LOAD-FAILED"); continue
        b = board_mib()
        base = chat(Q, 8)
        base_n = base["usage"]["prompt_tokens"]
        log(f"BASELINE {tag} text_prompt_n={base_n} board_mib={b}")
        for name, path in (("720p", shot720), ("1440p", shot1440)):
            if not os.path.exists(path):
                log(f"RESULT {tag}/{name} MISSING-FILE"); continue
            px = image_size(path)
            content = [{"type": "text", "text": Q},
                       {"type": "image_url",
                        "image_url": {"url": data_uri(path)}}]
            try:
                d = chat(content, 400)
            except Exception as e:
                log(f"RESULT {tag}/{name} FAILED {type(e).__name__} {e}")
                continue
            t = d.get("timings", {})
            n = d["usage"]["prompt_tokens"]
            msg = d["choices"][0]["message"]
            txt = msg.get("content") or ""
            think = msg.get("reasoning_content") or ""
            log("RESULT {}/{} px={}x{} png_bytes={} payload_bytes={} "
                "text_prompt_n={} img_prompt_n={} image_tokens={} "
                "prefill_tps={} prefill_s={} decode_tps={} predicted_n={} "
                "wall_s={} answer_chars={} think_chars={}".format(
                    tag, name, px[0], px[1], os.path.getsize(path),
                    d["_payload"], base_n, n, n - base_n,
                    round(t.get("prompt_per_second", 0), 1),
                    round(t.get("prompt_ms", 0) / 1000, 2),
                    round(t.get("predicted_per_second", 0), 2),
                    d["usage"]["completion_tokens"], d["_wall"],
                    len(txt), len(think)))
            with open(os.path.join(DATA, f"vision-{tag}-{name}.txt"), "w",
                      encoding="utf-8") as f:
                f.write(think + "\n---ANSWER---\n" + txt)
            log("  REPLY {}/{}| {}".format(tag, name,
                                           " ".join(txt.split())[:500]))
        kill_server()
    log("PHASE8B DONE")
    return 0


def image_size(path):
    """Minimal PNG header reader - no third-party dependency."""
    with open(path, "rb") as f:
        head = f.read(26)
    return (int.from_bytes(head[16:20], "big"),
            int.from_bytes(head[20:24], "big"))


if __name__ == "__main__":
    sys.exit(main())
