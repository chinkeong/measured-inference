#!/usr/bin/env python3
"""Stage-0 gate: can this box actually FETCH and HOLD what the interview chose?

    python scripts/check-request.py unsloth/Qwen3-30B-A3B-GGUF \
        --slug qwen3-30b-a3b --quant UD-Q4_K_XL --quant Q5_K_M

WHY THIS FILE EXISTS. Two blockers bite AFTER the Stage 0 interview closes, and
by then rule 27 has made asking illegal. Both are network-and-arithmetic;
neither needs a GPU; so both belong in the last minute of Stage 0, while asking
is still legal.

  1. A GATED repo passes the interview and fails at download time. The listing
     API answers 200 for a gated repo -- verified live: the tree of
     google/gemma-3-1b-it-qat-q4_0-gguf lists fine while a range request on the
     .gguf it lists returns 401 "Access to model ... is restricted". A
     successful listing is NOT proof of access. This repository has no
     downloader and no token plumbing to fall back on, so the discovery has to
     happen in the round where a token can still be asked for.

  2. NOTHING checks that the chosen quant FITS the card before it is fetched.
     `slack = BOARD - used` reads comfortably positive on a card whose real
     board is half the reference's -- the same failure scripts/lib/paths.py
     exists to prevent -- and on a 12 GB card facing a 27B Q4 that is 15+ GB
     downloaded, an hour of bandwidth spent, and every Stage-1 probe failing to
     start. The arithmetic that prevents it is four numbers wide.

WHAT IT REFUSES TO GUESS. Board size and desktop reserve come from
results/<slug>/machine.json through scripts/lib/paths.py or the fit is reported
UNKNOWN with the command that writes one -- never defaulted (rule 3, rule 14).
KV bytes/token comes from the model's real config.json using stage-1.md's
formula, or the fit is UNKNOWN. An UNKNOWN exits 2; a proven failure exits 1;
all-clear exits 0.

Weights alone are still checked against the budget when KV is unknown: if the
file by itself will not fit, that is PROVEN without the cache arithmetic, and
proving it costs nothing.

Stdlib only -- urllib, not requests. Stage 0 runs before `.venv` is guaranteed
to exist (setup.sh creates it, and a check that cannot run until after the
bootstrap cannot gate the bootstrap). Python 3.9+. Linux, macOS, Windows.
"""
import argparse
import json
import os
import re
import shutil
import sys
import urllib.error
import urllib.parse
import urllib.request

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "lib"))
import paths  # noqa: E402

HF_HOST = "https://huggingface.co"
API_MODEL = HF_HOST + "/api/models/%s"
API_TREE = API_MODEL + "/tree/main"
RESOLVE = HF_HOST + "/%s/resolve/main/%s"

# HF's tree API pages at 50 by default and answers with a Link: rel="next"
# header. A repo with more quants than that would silently list a subset, and a
# quant "missing from the listing" is exactly the false alarm this check must
# never raise. recursive=1 because shards live in subdirectories:
# bartowski/Qwen2.5-72B-Instruct-GGUF keeps 6 of its files in 3 subdirs.
TREE_PAGE = 1000

# Range request size, matching the interview's `curl -sI -r 0-1023`.
PROBE_BYTES = 1024

# KV cache element sizes in bytes. q8_0 is not 1.0: llama.cpp stores 32 values
# per block with an fp16 scale, 34 B per 32 values. The reference campaign's
# 34,816 B/token (vs 32,768 "nominal") is that 6.25% -- carried here so the
# fit check is held to the number the server actually allocates.
CACHE_TYPES = {"f32": (4.0, "f32"),
               "f16": (2.0, "f16"),
               "bf16": (2.0, "bf16"),
               "q8_0": (34.0 / 32.0, "q8_0 incl. block scales (34 B / 32 vals)")}

# Rule 21's cap. `-c` must clear the longest prompt PLUS the cap, so 16,384 is a
# floor for the smallest window a campaign can run its own suite at, not a
# recommendation. Campaigns with a real target window pass --c-min.
DEFAULT_C_MIN = 16384

OK, FAIL, UNKNOWN, SKIP = "OK", "FAIL", "UNKNOWN", "SKIP"


# ---------------------------------------------------------------------------
# reporting
# ---------------------------------------------------------------------------

class Report(object):
    """Six checks, each one line plus its evidence, then a one-line verdict."""

    def __init__(self, total):
        self.rows = []
        self.total = total

    def add(self, name, status, line, detail=None, fix=None):
        self.rows.append({"name": name, "status": status, "line": line,
                          "detail": list(detail or []), "fix": fix})
        return self.rows[-1]

    def render(self, out):
        for i, r in enumerate(self.rows, 1):
            out.write(ascii_only("  [%d/%d] %-8s %-7s %s\n"
                                 % (i, self.total, r["name"], r["status"],
                                    r["line"])))
            for d in r["detail"]:
                out.write(ascii_only("           %s\n" % d))
            if r["fix"]:
                out.write(ascii_only("           FIX: %s\n" % r["fix"]))
        out.write("\n")

    def exit_code(self):
        if any(r["status"] == FAIL for r in self.rows):
            return 1
        if any(r["status"] == UNKNOWN for r in self.rows):
            return 2
        return 0

    def verdict(self):
        bad = [r for r in self.rows if r["status"] == FAIL]
        unk = [r for r in self.rows if r["status"] == UNKNOWN]
        if bad:
            return ("VERDICT: BLOCKED -- %s. %s"
                    % (", ".join(r["name"].lower() for r in bad),
                       bad[0]["fix"] or bad[0]["line"]))
        if unk:
            return ("VERDICT: UNPROVEN -- %s could not be established. %s"
                    % (", ".join(r["name"].lower() for r in unk),
                       unk[0]["fix"] or "Resolve it before the interview closes."))
        return "VERDICT: CLEAR -- access proven, roster resolved, everything fits."


def ascii_only(text):
    """Nothing non-ASCII ever reaches the console.

    Half of what this script prints is quoted from somewhere else -- paths.py's
    SystemExit text, HF's x-error-message header, a file name from the listing.
    PowerShell 5.1's default console is cp1252 and prints an em dash as a
    replacement glyph; a repo id in another script could raise
    UnicodeEncodeError outright and lose the finding with it. The line is worth
    more than the punctuation.
    """
    for bad, good in ((u"—", "--"), (u"–", "-"),
                      (u"‘", "'"), (u"’", "'"),
                      (u"“", '"'), (u"”", '"')):
        text = text.replace(bad, good)
    return text.encode("ascii", "replace").decode("ascii")


def human(nbytes):
    if nbytes is None:
        return "?"
    g = nbytes / (1024.0 ** 3)
    if g >= 1.0:
        return "%.2f GiB" % g
    return "%.1f MiB" % (nbytes / (1024.0 ** 2))


def mib(nbytes):
    return nbytes / (1024.0 ** 2)


def comma(x):
    return "{:,}".format(int(round(x)))


# ---------------------------------------------------------------------------
# HTTP -- stdlib only
# ---------------------------------------------------------------------------

class NetworkDown(Exception):
    """No answer at all: DNS, refused, timeout. Distinct from an HTTP error,
    which IS an answer and is usually the finding we came for."""


class HttpFail(Exception):
    def __init__(self, code, reason, message=""):
        Exception.__init__(self, "%s %s" % (code, reason))
        self.code = code
        self.reason = reason
        self.message = message


class _Redirects(urllib.request.HTTPRedirectHandler):
    """Follow redirects, but never carry the token to another host.

    /resolve/main/<file> answers 302 to a pre-signed CDN URL on a different
    host. The signature is the credential there; forwarding Authorization as
    well is both a token leak to a third party and a way to turn a working
    fetch into a 400. Range survives on purpose -- CPython only strips
    Content-Length and Content-Type across a redirect -- which is what makes
    the 206 at the end real proof that bytes were served.
    """

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        new = urllib.request.HTTPRedirectHandler.redirect_request(
            self, req, fp, code, msg, headers, newurl)
        if new is None:
            return None
        if (urllib.parse.urlsplit(newurl).hostname
                != urllib.parse.urlsplit(req.full_url).hostname):
            for k in list(new.headers):
                if k.lower() == "authorization":
                    del new.headers[k]
            new.unredirected_hdrs.pop("Authorization", None)
        return new


_OPENER = urllib.request.build_opener(_Redirects())


def _open(url, token=None, extra=None, timeout=30):
    req = urllib.request.Request(url)
    req.add_header("User-Agent", "measured-inference/check-request")
    if token:
        req.add_header("Authorization", "Bearer " + token)
    for k, v in (extra or {}).items():
        req.add_header(k, v)
    try:
        return _OPENER.open(req, timeout=timeout)
    except urllib.error.HTTPError as exc:
        # HF puts the human reason here, and it is the difference between
        # "gated" and "you typed the repo name wrong".
        msg = (exc.headers.get("x-error-message")
               or exc.headers.get("X-Error-Message") or "")
        raise HttpFail(exc.code, exc.reason, msg)
    except urllib.error.URLError as exc:
        raise NetworkDown(str(getattr(exc, "reason", exc)))
    except OSError as exc:                      # socket.timeout, ssl errors
        raise NetworkDown(str(exc))


def get_json(url, token=None, timeout=30):
    with _open(url, token, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8")), r.headers


# ---------------------------------------------------------------------------
# the token
# ---------------------------------------------------------------------------

TOKEN_ENV = ("HF_TOKEN", "HUGGING_FACE_HUB_TOKEN", "HUGGINGFACE_TOKEN")


def find_token(explicit=None, allow_env=True):
    """(token, where-it-came-from). The token itself is never printed."""
    if explicit:
        return explicit.strip(), "--token"
    if not allow_env:
        return None, "none (--no-token)"
    for name in TOKEN_ENV:
        val = os.environ.get(name)
        if val and val.strip():
            return val.strip(), "$" + name
    cached = os.path.join(os.path.expanduser("~"), ".cache", "huggingface",
                          "token")
    if os.path.isfile(cached):
        try:
            with open(cached, "r", encoding="utf-8") as fh:
                val = fh.read().strip()
            if val:
                return val, "~/.cache/huggingface/token"
        except OSError:
            pass
    return None, "none found"


def token_label(token, where):
    if not token:
        return "anonymous (%s)" % where
    return "token from %s (%d chars, not printed)" % (where, len(token))


# ---------------------------------------------------------------------------
# check 1 -- the slug
# ---------------------------------------------------------------------------

def parse_repo(raw):
    """'https://huggingface.co/unsloth/Foo-GGUF/tree/main' -> 'unsloth/Foo-GGUF'."""
    s = raw.strip()
    if "://" in s:
        s = urllib.parse.urlsplit(s).path
    s = s.strip("/")
    for marker in ("/tree/", "/blob/", "/resolve/"):
        if marker in s:
            s = s.split(marker, 1)[0]
    return s


def derive_slug(repo):
    """AGENTS.md LAYOUT: the repo NAME, lowercased, -GGUF/-gguf dropped."""
    name = repo.rstrip("/").split("/")[-1].lower()
    if name.endswith("-gguf"):
        name = name[:-len("-gguf")]
    return name


def check_slug(rep, repo, given):
    derived = derive_slug(repo)
    slug = given or derived
    bad = None
    if not slug:
        bad = "empty"
    elif "/" in slug or "\\" in slug:
        bad = "not a single path component (it contains a separator)"
    elif slug in (".", "..") or slug.startswith("."):
        bad = "not a usable directory name"
    if bad:
        rep.add("SLUG", FAIL, "%r is %s" % (slug, bad),
                fix="use --slug %s" % derived)
        return slug
    if slug == derived:
        rep.add("SLUG", OK, "%s   (derived from %s by AGENTS.md's naming rule)"
                % (slug, repo))
        return slug
    # A restart must reuse the recorded slug verbatim even where the rule would
    # now derive something else (AGENTS.md, RESUMING A CRASHED CAMPAIGN).
    log = os.path.join(paths.repo_root(), "results", slug, "campaign.md")
    if os.path.isfile(log):
        rep.add("SLUG", OK, "%s   (existing campaign, reused verbatim)" % slug,
                ["the naming rule would derive %r; results/%s/campaign.md "
                 "already exists, so the recorded slug wins" % (derived, slug)])
    else:
        rep.add("SLUG", FAIL,
                "%r does not match the naming rule and no campaign uses it"
                % slug,
                ["AGENTS.md LAYOUT: repo name, lowercased, -GGUF/-gguf dropped"],
                fix="use --slug %s, or create results/%s/campaign.md first"
                    % (derived, slug))
    return slug


# ---------------------------------------------------------------------------
# check 2 -- the listing
# ---------------------------------------------------------------------------

SHARD = re.compile(r"-\d{5}-of-\d{5}(?=\.gguf$)", re.I)


def list_tree(repo, token):
    """Every file in the repo tree, following Link: rel=next. Recursive."""
    url = API_TREE % repo + "?recursive=1&limit=%d" % TREE_PAGE
    out = []
    pages = 0
    while url:
        with _open(url, token) as r:
            page = json.loads(r.read().decode("utf-8"))
            link = r.headers.get("Link") or ""
        out.extend(e for e in page if e.get("type") == "file")
        pages += 1
        m = re.search(r'<([^>]+)>;\s*rel="next"', link)
        url = m.group(1) if m and pages < 50 else None
    return out


def is_mmproj(path):
    return "mmproj" in os.path.basename(path).lower()


def group_gguf(entries):
    """GGUF files, with -00001-of-00003 shards folded into one candidate.

    A sharded quant is one download and one resident file set; sizing the first
    shard alone understates a 70B by a factor of three.
    """
    groups = {}
    for e in entries:
        path = e.get("path") or ""
        if not path.lower().endswith(".gguf"):
            continue
        size = e.get("size")
        if not isinstance(size, int):
            size = (e.get("lfs") or {}).get("size")
        key = SHARD.sub("", path)
        g = groups.setdefault(key, {"name": key, "files": [], "bytes": 0,
                                    "sized": True, "mmproj": is_mmproj(path)})
        g["files"].append(path)
        if isinstance(size, int):
            g["bytes"] += size
        else:
            g["sized"] = False
    for g in groups.values():
        g["files"].sort()
        g["shards"] = len(g["files"])
    return sorted(groups.values(), key=lambda g: g["name"].lower())


def check_listing(rep, repo, token, offline):
    if offline:
        # UNKNOWN, not SKIP: the check APPLIES, it just did not run. SKIP is
        # reserved for "not applicable", and only UNKNOWN keeps exit 0 out of
        # reach -- an all-clear must never be reachable with access unproven.
        rep.add("LISTING", UNKNOWN,
                "--no-network: the repo tree was not fetched")
        return None
    try:
        entries = list_tree(repo, token)
    except NetworkDown as exc:
        rep.add("LISTING", UNKNOWN, "no network: %s" % exc,
                ["nothing about this repo can be established offline"],
                fix="re-run with a network, or --no-network to skip the "
                    "network checks deliberately")
        return None
    except HttpFail as exc:
        detail = [exc.message] if exc.message else []
        fix = "check the repo id"
        if exc.code in (401, 403):
            # HF answers 401 for a repo that does not exist as well as for one
            # you may not see -- it will not confirm which, so neither will we.
            fix = ("the LISTING itself is refused. HF returns 401 both for a "
                   "misspelled repo id and for a private one, and does not say "
                   "which: re-check the spelling of %r first, then supply "
                   "--token" % repo)
        rep.add("LISTING", FAIL, "GET /api/models/%s/tree/main -> %d %s"
                % (repo, exc.code, exc.reason), detail, fix=fix)
        return None

    groups = group_gguf(entries)
    ggufs = [g for g in groups if not g["mmproj"]]
    projs = [g for g in groups if g["mmproj"]]
    if not groups:
        rep.add("LISTING", FAIL, "resolved, but holds no .gguf at all",
                ["%d files in the tree" % len(entries)],
                fix="is this the base repo rather than the GGUF one?")
        return groups

    total = sum(g["bytes"] for g in groups)
    rep.add("LISTING", OK,
            "%d GGUF candidate%s (%s total), %s"
            % (len(ggufs), "" if len(ggufs) == 1 else "s", human(total),
               ("mmproj present: " + projs[0]["name"]) if projs
               else "NO mmproj -- vision work is not possible from this repo"),
            ["%-52s %10s%s" % (g["name"], human(g["bytes"]),
                               "  (%d shards)" % g["shards"]
                               if g["shards"] > 1 else "")
             for g in groups])
    return groups


# ---------------------------------------------------------------------------
# check 3 -- access, PROVEN
# ---------------------------------------------------------------------------

def range_probe(repo, filename, token):
    """(status, total_bytes, first_bytes). A real GET, a real 1 KiB served."""
    url = RESOLVE % (repo, urllib.parse.quote(filename))
    with _open(url, token, {"Range": "bytes=0-%d" % (PROBE_BYTES - 1)}) as r:
        body = r.read(PROBE_BYTES)
        cr = r.headers.get("Content-Range") or ""
        m = re.search(r"/(\d+)\s*$", cr)
        status = r.status if hasattr(r, "status") else r.getcode()
        return status, (int(m.group(1)) if m else None), body


def check_access(rep, repo, groups, chosen, token, where, offline, all_files):
    if offline:
        rep.add("ACCESS", UNKNOWN, "--no-network: access was NOT proven")
        return
    if groups is None:
        rep.add("ACCESS", UNKNOWN, "not attempted (no listing to choose a file "
                                   "from)")
        return
    pool = chosen or [g for g in groups if not g["mmproj"]] or groups
    if not pool:
        rep.add("ACCESS", UNKNOWN, "no file to probe")
        return
    targets = pool if all_files else pool[:1]
    detail = ["identity: " + token_label(token, where)]
    worst = None
    for g in targets:
        fn = g["files"][0]
        try:
            status, total, body = range_probe(repo, fn, token)
        except NetworkDown as exc:
            rep.add("ACCESS", UNKNOWN,
                    "no network during the range request: %s" % exc, detail)
            return
        except HttpFail as exc:
            worst = worst or exc
            detail.append("%-44s -> %d %s" % (fn, exc.code, exc.reason))
            if exc.message:
                detail.append("  %s" % exc.message)
            continue
        note = ""
        if body[:4] == b"GGUF":
            note = "  magic GGUF ok"
        elif body:
            note = "  WARNING: first bytes are not GGUF magic"
        if total is not None and g["shards"] == 1 and total != g["bytes"]:
            note += ("  WARNING: server says %s B, listing said %s B"
                     % (comma(total), comma(g["bytes"])))
        detail.append("%-44s -> %d, %d bytes served%s"
                      % (fn, status, len(body), note))

    if worst is None:
        rep.add("ACCESS", OK,
                "range request served real bytes (%d file%s probed)"
                % (len(targets), "" if len(targets) == 1 else "s"), detail)
        return
    if worst.code in (401, 403):
        fix = ("THE TRAP: the listing above succeeded and the download will "
               "not. Accept the licence at %s/%s, create a read token, and "
               "re-run with --token <tok> -- ASK NOW, while the interview is "
               "still open (rule 27)." % (HF_HOST, repo))
        if token:
            fix = ("the %s token was sent and still refused: this account has "
                   "no access to %s. Accept the licence on the model page, or "
                   "pick another repo -- ASK NOW (rule 27)." % (where, repo))
        rep.add("ACCESS", FAIL, "GATED: %d %s on a file the listing shows"
                % (worst.code, worst.reason), detail, fix=fix)
    elif worst.code == 404:
        rep.add("ACCESS", FAIL, "404 on a file the listing shows", detail,
                fix="the tree and the resolve endpoint disagree; re-check the "
                    "revision")
    elif worst.code == 429:
        rep.add("ACCESS", UNKNOWN, "429 rate-limited -- access NOT proven",
                detail, fix="wait and re-run; a token raises the limit")
    else:
        rep.add("ACCESS", FAIL, "%d %s" % (worst.code, worst.reason), detail,
                fix="the download will fail the same way")


# ---------------------------------------------------------------------------
# check 4 -- every named quant exists
# ---------------------------------------------------------------------------

def label_re(label):
    """A quant label is a delimited token in the file name, not a substring.

    Boundaries matter both ways: Q4_K_M must not match Q4_K_M_XL, and IQ4_XS
    SHOULD match both a plain and a UD-IQ4_XS file -- which is a real ambiguity
    and is reported as one rather than resolved by picking.
    """
    return re.compile(r"(?:^|[-._/])" + re.escape(label) + r"(?:$|[-._])",
                      re.IGNORECASE)


def _stem(name):
    base = os.path.basename(name)
    return base[:-len(".gguf")] if base.lower().endswith(".gguf") else base


def match_quant(groups, label):
    exact = [g for g in groups
             if os.path.basename(g["name"]).lower()
             in (label.lower(), label.lower() + ".gguf")]
    if exact:
        return exact
    rx = label_re(label)
    return [g for g in groups if rx.search(_stem(g["name"]))]


def check_quants(rep, groups, wanted):
    if not wanted:
        rep.add("QUANTS", SKIP,
                "no --quant given: every listed GGUF is treated as a candidate")
        return [g for g in (groups or []) if not g["mmproj"]]
    if groups is None:
        rep.add("QUANTS", UNKNOWN, "no listing to check %d name%s against"
                % (len(wanted), "" if len(wanted) == 1 else "s"))
        return []
    pool = [g for g in groups if not g["mmproj"]]
    chosen, bad, detail = [], [], []
    for label in wanted:
        hits = match_quant(pool, label)
        if not hits:
            bad.append(label)
            detail.append("%-18s NOT IN THE LISTING" % label)
            detail.append("  the repo offers: %s"
                          % (", ".join(_stem(g["name"]) for g in pool[:6])
                             or "-"))
        elif len(hits) > 1:
            bad.append(label)
            detail.append("%-18s AMBIGUOUS -- matches %d files"
                          % (label, len(hits)))
            for g in hits:
                detail.append("  %s" % g["name"])
        else:
            chosen.append(hits[0])
            detail.append("%-18s -> %-42s %s"
                          % (label, hits[0]["name"], human(hits[0]["bytes"])))
    if bad:
        rep.add("QUANTS", FAIL, "%d of %d named quant%s unresolved"
                % (len(bad), len(wanted), "" if len(wanted) == 1 else "s"),
                detail,
                fix="fix %s -- a typo here is a download that 404s in Stage 1"
                    % ", ".join(repr(b) for b in bad))
    else:
        rep.add("QUANTS", OK,
                "the named quant exists in the listing" if len(wanted) == 1
                else "all %d named quants exist in the listing" % len(wanted),
                detail)
    return chosen


# ---------------------------------------------------------------------------
# check 5 -- the fit
# ---------------------------------------------------------------------------

def fetch_config(repo, base_repo, token, offline, notes):
    """The model's config.json, and where it came from.

    Quant-only repos usually carry no config.json (stage-1.md says so), and the
    base repo is named in the GGUF repo's own card metadata -- so that lookup
    is one extra API call, not a guess.
    """
    if offline:
        notes.append("--no-network: config.json not fetched")
        return None, None
    tries = [(repo, RESOLVE % (repo, "config.json"))]
    if base_repo and base_repo != repo:
        tries.append((base_repo, RESOLVE % (base_repo, "config.json")))
    for name, url in tries:
        try:
            with _open(url, token) as r:
                return json.loads(r.read().decode("utf-8")), name
        except HttpFail as exc:
            notes.append("config.json from %s -> %d %s%s"
                         % (name, exc.code, exc.reason,
                            ("  " + exc.message) if exc.message else ""))
        except NetworkDown as exc:
            notes.append("config.json: no network (%s)" % exc)
            return None, None
        except ValueError as exc:
            notes.append("config.json from %s is not JSON: %s" % (name, exc))
    return None, None


def kv_arithmetic(cfg, elem_bytes, elem_label, c_min):
    """stage-1.md's formula, shown term by term.

        KV bytes/token = 2 x full-attention layers x n_kv_heads x head_dim
                           x bytes-per-element

    2 = K and V. For a plain transformer every layer is a full-attention layer.
    For hybrids only the full-attention ones count; stage-1.md requires the
    other kinds be carried as SEPARATE constants rather than folded into the
    per-token figure, which is what fixed_mib below is.
    """
    out = {"lines": [], "notes": [], "bytes_per_token": None, "fixed_mib": 0.0}
    if not isinstance(cfg, dict):
        return out
    src = cfg
    for nest in ("text_config", "llm_config", "language_config"):
        if "num_hidden_layers" not in src and isinstance(cfg.get(nest), dict):
            src = cfg[nest]
            out["notes"].append("read the nested %r block (multimodal config)"
                                % nest)
            break

    n_layer = src.get("num_hidden_layers")
    n_kv = src.get("num_key_value_heads", src.get("num_attention_heads"))
    head_dim = src.get("head_dim")
    if not head_dim and src.get("hidden_size") and src.get("num_attention_heads"):
        head_dim = src["hidden_size"] // src["num_attention_heads"]
        out["notes"].append("head_dim absent: derived hidden_size/"
                            "num_attention_heads = %d/%d = %d"
                            % (src["hidden_size"], src["num_attention_heads"],
                               head_dim))
    if not all(isinstance(v, int) and v > 0 for v in (n_layer, n_kv, head_dim)):
        out["notes"].append("config.json lacks num_hidden_layers / "
                            "num_key_value_heads / head_dim")
        return out

    # Which layers actually hold a per-token K/V. Getting this wrong is not a
    # rounding error: counting gemma-3's 62 layers as full attention instead of
    # its 10 overstates KV by 4.7x and rejects a quant that fits. Overstating
    # fails safe against a spill and UNSAFE against the campaign -- a Stage-0
    # gate that vetoes a workable quant is worse than no gate.
    full, linear, swa = n_layer, 0, 0
    how = "all %d layers (plain transformer)" % n_layer
    types = src.get("layer_types")
    interval = src.get("full_attention_interval")
    swa_pattern = src.get("sliding_window_pattern")
    win = src.get("sliding_window")
    swa_on = src.get("use_sliding_window", True) is not False and bool(win)
    if isinstance(types, list) and types:
        full = sum(1 for t in types if "full" in str(t))
        swa = sum(1 for t in types if "sliding" in str(t))
        linear = len(types) - full - swa
        how = "%d of %d layers, counted from layer_types" % (full, len(types))
    elif isinstance(interval, int) and interval > 1:
        full = n_layer // interval
        linear = n_layer - full
        how = ("%d of %d layers (full_attention_interval %d -- the other %d "
               "are linear/gated-delta and carry a FIXED state)"
               % (full, n_layer, interval, linear))
    elif isinstance(swa_pattern, int) and swa_pattern > 1 and swa_on:
        # gemma-3: a layer is sliding unless (idx + 1) % pattern == 0.
        full = n_layer // swa_pattern
        swa = n_layer - full
        how = ("%d of %d layers (sliding_window_pattern %d -- every %dth layer "
               "is global, the other %d slide over %s tokens)"
               % (full, n_layer, swa_pattern, swa_pattern, swa, comma(win)))

    bpt = 2 * full * n_kv * head_dim * elem_bytes
    out["bytes_per_token"] = bpt
    out["full_attn_layers"] = full
    out["lines"].append(
        "KV bytes/token = 2 x %d full-attn x %d kv-heads x %d head-dim x %g B"
        " = %s" % (full, n_kv, head_dim, elem_bytes, comma(bpt)))
    out["lines"].append("  full-attention layers: %s" % how)
    out["lines"].append("  cache element: %s" % elem_label)
    out["lines"].append("  KV at c=%s: %s B = %s MiB"
                        % (comma(c_min), comma(bpt * c_min),
                           comma(mib(bpt * c_min))))

    # sliding-window layers cap at their window: a constant, not a per-token
    # cost (stage-1.md).
    if swa and isinstance(win, int) and win > 0:
        fixed = 2 * swa * n_kv * head_dim * elem_bytes * min(win, c_min)
        out["fixed_mib"] += mib(fixed)
        out["lines"].append("  + %d sliding-window layers capped at %s tokens "
                            "= %s MiB (constant)"
                            % (swa, comma(min(win, c_min)), comma(mib(fixed))))
        full_if_unsliced = 2 * (full + swa) * n_kv * head_dim * elem_bytes
        out["lines"].append("  llama-server --swa-full defeats that cap: KV "
                            "would be %s B/token = %s MiB at c=%s"
                            % (comma(full_if_unsliced),
                               comma(mib(full_if_unsliced * c_min)),
                               comma(c_min)))
        out["swa_full_bytes_per_token"] = full_if_unsliced
    elif swa:
        out["notes"].append("%d sliding-window layers found but no "
                            "sliding_window size: their cost is NOT counted"
                            % swa)

    # gated-delta / mamba layers: a fixed per-sequence state, context-independent
    lin_keys = ("linear_conv_kernel_dim", "linear_key_head_dim",
                "linear_num_key_heads", "linear_num_value_heads",
                "linear_value_head_dim")
    if linear > 0 and all(isinstance(src.get(k), int) for k in lin_keys):
        k = src["linear_conv_kernel_dim"]
        nk, dk = src["linear_num_key_heads"], src["linear_key_head_dim"]
        nv, dv = src["linear_num_value_heads"], src["linear_value_head_dim"]
        elems = k * (2 * nk * dk + nv * dv) + nv * dv * dk
        total = elems * 4 * linear            # mamba_ssm_dtype float32
        out["fixed_mib"] += mib(total)
        out["lines"].append(
            "  + %d linear layers x (conv %d x (2x%dx%d + %dx%d) + state "
            "%dx%dx%d) x 4 B = %s MiB (context-independent)"
            % (linear, k, nk, dk, nv, dv, nv, dv, dk, comma(mib(total))))
    elif linear > 0:
        out["notes"].append("%d non-full-attention layers carry a fixed state "
                            "this config does not describe: NOT counted, so "
                            "the fit below is optimistic by that much" % linear)
    return out


def budget(slug, notes):
    """(board_mib, reserve_max_mib) from machine.json, or (None, None).

    paths.py raises SystemExit when the file is missing -- correct for a run
    that is about to measure, wrong for a check whose entire job is to report
    what is missing. Caught here, reported as UNKNOWN, never defaulted.
    """
    try:
        board = paths.board_total_mib(slug)
        reserve = paths.desktop_reserve_mib(slug)
    except SystemExit as exc:
        text = str(exc).strip()
        notes.append("machine.json: %s"
                     % (text.splitlines()[0] if text else "unavailable"))
        return None, None
    notes.append("machine.json: board %s MiB, desktop reserve max %s MiB "
                 "(n=%s, measured %s)"
                 % (comma(board), comma(reserve["max"]), reserve["n"],
                    reserve["date"]))
    return board, reserve["max"]


def check_fit(rep, cands, projector, kv, board, reserve, c_min, notes, named,
              slug="<slug>"):
    if not cands:
        # No files, but the arithmetic that WOULD have been applied is still
        # the point of this check: an operator can check the KV formula and
        # the budget by eye without a listing (rule 1 -- derived arithmetic is
        # publishable only when it is shown).
        rep.add("FIT", UNKNOWN, "no candidate files to size",
                list(kv.get("lines", [])) + list(notes)
                + ["NOTE: %s" % n for n in kv.get("notes", [])])
        return []
    proj_mib = mib(projector["bytes"]) if projector else 0.0
    fixed = kv.get("fixed_mib", 0.0)
    bpt = kv.get("bytes_per_token")

    detail = list(kv.get("lines", []))
    detail.extend(notes)
    for n in kv.get("notes", []):
        detail.append("NOTE: %s" % n)
    if projector:
        detail.append("projector %s = %s MiB (resident whenever vision runs)"
                      % (projector["name"], comma(proj_mib)))
    # Everything this sum leaves out, said out loud. A "FITS, 200 MiB spare"
    # that omits the compute buffer is the same unfalsifiable number rule 3
    # forbids -- and naming a constant for it would be inventing one.
    detail.append("NOT counted: llama.cpp's compute/output buffers (hundreds of "
                  "MiB, size unknown until the server logs it), nor a "
                  "speculative drafter's weights -- rule 13's scope is "
                  "file+drafter+projector+desktop. Treat a thin margin as "
                  "UNPROVEN until Stage 1 reads the server's own KV figure.")

    rows, worst_named, any_fit = [], None, False
    if board is None:
        # No board size: the sum is still worth printing, but nothing may be
        # called a fit. This is the branch rule 3 exists for.
        for g in cands:
            w = mib(g["bytes"])
            kvm = mib(bpt * c_min) if bpt else None
            rows.append({"name": g["name"], "weights_mib": round(w, 1),
                         "kv_mib": None if kvm is None else round(kvm, 1),
                         "projector_mib": round(proj_mib, 1),
                         "fixed_mib": round(fixed, 1),
                         "total_mib": round(w + (kvm or 0) + proj_mib + fixed, 1),
                         "budget_mib": None, "verdict": UNKNOWN})
            detail.append("%-44s %9s w + %9s kv + %6s proj + %5s fix = %9s MiB"
                          "   ? no board size"
                          % (_stem(g["name"]), comma(w),
                             comma(kvm) if kvm is not None else "?",
                             comma(proj_mib), comma(fixed),
                             comma(w + (kvm or 0) + proj_mib + fixed)))
        rep.add("FIT", UNKNOWN, "no machine.json: this card is unmeasured",
                detail,
                fix="python scripts/detect-machine.py --slug %s   (writes "
                    "results/%s/machine.json; a guessed board is how a "
                    "spilling window gets stamped PASS -- rule 13)"
                    % (slug, slug))
        return rows

    avail = board - reserve
    detail.insert(0, "budget = %s board - %s desktop reserve(max) = %s MiB"
                  % (comma(board), comma(reserve), comma(avail)))
    for g in cands:
        w = mib(g["bytes"])
        kvm = mib(bpt * c_min) if bpt else None
        floor = w + proj_mib + fixed
        total = floor + (kvm or 0.0)
        if kvm is None:
            # Weights alone can still PROVE a miss without the cache term.
            verdict = "SPILLS" if floor > avail else UNKNOWN
            mark = ("SPILLS on weights alone by %s MiB" % comma(floor - avail)
                    if verdict == "SPILLS" else "? KV unknown")
        else:
            verdict = "FITS" if total <= avail else "SPILLS"
            mark = ("FITS, %s MiB spare" % comma(avail - total)
                    if verdict == "FITS"
                    else "SPILLS by %s MiB" % comma(total - avail))
        any_fit = any_fit or verdict == "FITS"
        rows.append({"name": g["name"], "weights_mib": round(w, 1),
                     "kv_mib": None if kvm is None else round(kvm, 1),
                     "projector_mib": round(proj_mib, 1),
                     "fixed_mib": round(fixed, 1),
                     "total_mib": round(total, 1), "budget_mib": round(avail, 1),
                     "verdict": verdict})
        detail.append("%-44s %9s w + %9s kv + %6s proj + %5s fix = %9s   %s"
                      % (_stem(g["name"]), comma(w),
                         comma(kvm) if kvm is not None else "?",
                         comma(proj_mib), comma(fixed), comma(total), mark))
        if named and verdict != "FITS" and worst_named is None:
            worst_named = (g["name"], verdict)

    if worst_named:
        name, verdict = worst_named
        if verdict == "SPILLS":
            rep.add("FIT", FAIL, "%s does not fit this card at c=%s"
                    % (_stem(name), comma(c_min)), detail,
                    fix="choose a smaller quant, lower --c-min, or accept the "
                        "spill knowingly -- do NOT download it to find out")
        else:
            rep.add("FIT", UNKNOWN, "%s cannot be sized: KV bytes/token unknown"
                    % _stem(name), detail,
                    fix="pass --config <config.json> or --base-repo <org/model>"
                        " -- an unfitted download is the expensive mistake")
    elif bpt is None:
        rep.add("FIT", UNKNOWN, "weights fit, but KV bytes/token is unknown",
                detail,
                fix="pass --config <config.json> or --base-repo <org/model>")
    elif not any_fit:
        rep.add("FIT", FAIL, "nothing in this repo fits at c=%s" % comma(c_min),
                detail, fix="this repo is the wrong size for this card")
    else:
        n = sum(1 for r in rows if r["verdict"] == "FITS")
        rep.add("FIT", OK, "%d of %d candidate%s fit at c=%s"
                % (n, len(rows), "" if len(rows) == 1 else "s", comma(c_min)),
                detail)
    return rows


# ---------------------------------------------------------------------------
# check 6 -- disk
# ---------------------------------------------------------------------------

def models_dir(slug):
    """Where a download would land: campaign.json model_dir, $MODEL_DIR, then
    <repo>/models -- paths.model_path()'s own order. It cannot be asked
    directly: model_path() resolves files that EXIST, and nothing has been
    downloaded yet. That is the whole point of this check."""
    try:
        camp = paths.load_campaign(slug)
    except SystemExit:
        camp = {}
    for src, root in (("campaign.json model_dir", camp.get("model_dir")),
                      ("$MODEL_DIR", os.environ.get("MODEL_DIR")),
                      ("<repo>/models", os.path.join(paths.repo_root(),
                                                     "models"))):
        if root:
            return os.path.abspath(os.path.expanduser(root)), src
    return None, None


def check_disk(rep, slug, cands, projector, named):
    root, src = models_dir(slug)
    if not root:
        rep.add("DISK", UNKNOWN, "no models directory could be resolved")
        return
    probe, missing = root, False
    while not os.path.isdir(probe):
        missing = True
        parent = os.path.dirname(probe)
        if parent == probe:
            break
        probe = parent
    try:
        free = shutil.disk_usage(probe).free
    except OSError as exc:
        rep.add("DISK", UNKNOWN, "cannot stat %s: %s" % (probe, exc))
        return
    detail = ["target: %s   (%s)%s"
              % (root, src,
                 "  -- does not exist yet, will be created" if missing else ""),
              "free:   %s  (on the volume holding %s)" % (human(free), probe)]
    if not named or not cands:
        why = ("no --quant given" if not named
               else "the named quants did not resolve, so nothing has a size")
        if cands:
            detail.append("%s: the largest single candidate is %s"
                          % (why, human(max(g["bytes"] for g in cands))))
        else:
            detail.append(why)
        rep.add("DISK", SKIP, "%s free; nothing sized to check it against"
                % human(free), detail)
        return
    need = sum(g["bytes"] for g in cands) + (projector["bytes"] if projector
                                            else 0)
    want = int(need * 1.05)
    detail.append("need:   %s for %d file set%s%s, +5%% margin = %s"
                  % (human(need), len(cands), "" if len(cands) == 1 else "s",
                     " + projector" if projector else "", human(want)))
    if free >= want:
        rep.add("DISK", OK, "%s free, %s needed" % (human(free), human(want)),
                detail)
    else:
        rep.add("DISK", FAIL, "%s free, %s needed -- short by %s"
                % (human(free), human(want), human(want - free)), detail,
                fix="free space under %s, or point campaign.json model_dir at "
                    "another volume" % root)


# ---------------------------------------------------------------------------

def main(argv=None):
    ap = argparse.ArgumentParser(
        prog="check-request.py",
        description="Stage-0 gate: prove repo ACCESS and quant FIT while "
                    "asking is still legal (rule 27).",
        epilog="""examples:
  python scripts/check-request.py Qwen/Qwen2.5-0.5B-Instruct-GGUF
  python scripts/check-request.py unsloth/Foo-27B-GGUF --slug foo-27b \\
      --quant UD-IQ4_XS --quant Q4_K_M --c-min 32768 --cache-type q8_0

exit: 0 everything proved   1 a check FAILED   2 nothing failed but something
is UNKNOWN -- an unproven access or an unsized fit is not a pass.""",
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("repo", help="HF repo id or URL, e.g. unsloth/Foo-GGUF")
    ap.add_argument("--slug", help="campaign slug; derived from the repo name "
                                   "when omitted")
    ap.add_argument("--quant", action="append", default=[], metavar="LABEL",
                    help="a quant to check (repeatable): a label like "
                         "UD-IQ4_XS, or a full file name")
    ap.add_argument("--base-repo", metavar="ORG/MODEL",
                    help="where config.json lives when the GGUF repo has none; "
                         "read from the repo card when omitted")
    ap.add_argument("--config", metavar="FILE",
                    help="a local config.json, instead of fetching one")
    ap.add_argument("--c-min", type=int, default=DEFAULT_C_MIN, metavar="N",
                    help="smallest context the campaign must run at "
                         "(default %d, rule 21's cap)" % DEFAULT_C_MIN)
    ap.add_argument("--cache-type", default="f16", choices=sorted(CACHE_TYPES),
                    help="KV cache element type (default f16)")
    ap.add_argument("--token", metavar="TOK", help="HF access token")
    ap.add_argument("--no-token", action="store_true",
                    help="ignore any token in the environment (prove the "
                         "anonymous case)")
    ap.add_argument("--no-projector", action="store_true",
                    help="do not charge the mmproj against the budget")
    ap.add_argument("--range-all", action="store_true",
                    help="range-probe every chosen file, not just the first")
    ap.add_argument("--no-network", action="store_true",
                    help="skip every network check deliberately")
    ap.add_argument("--json", action="store_true",
                    help="also print the machine-readable record")
    a = ap.parse_args(argv)

    repo = parse_repo(a.repo)
    if repo.count("/") > 1 or not repo:
        ap.error("%r is not an HF repo id (org/name)" % a.repo)
    token, where = find_token(a.token, allow_env=not a.no_token)
    elem_bytes, elem_label = CACHE_TYPES[a.cache_type]

    out = sys.stdout
    out.write("\ncheck-request  %s\n" % repo)
    out.write("               %s, c_min %s, KV %s\n\n"
              % (token_label(token, where), comma(a.c_min), a.cache_type))

    rep = Report(6)
    slug = check_slug(rep, repo, a.slug)

    info = {}
    if not a.no_network:
        try:
            info, _ = get_json(API_MODEL % repo, token)
        except (HttpFail, NetworkDown):
            info = {}

    groups = check_listing(rep, repo, token, a.no_network)
    if info.get("gated"):
        rep.rows[-1]["detail"].append(
            "the repo card says gated=%r -- the range check below is what "
            "settles it" % info["gated"])

    chosen = check_quants(rep, groups, a.quant)
    check_access(rep, repo, groups, chosen, token, where, a.no_network,
                 a.range_all)

    projector = None
    if groups and not a.no_projector:
        projs = [g for g in groups if g["mmproj"]]
        projector = projs[0] if projs else None

    notes = []
    cfg, cfg_src = None, None
    if a.config:
        try:
            with open(a.config, "r", encoding="utf-8-sig") as fh:
                cfg = json.load(fh)
            cfg_src = a.config
        except (OSError, ValueError) as exc:
            notes.append("--config %s unreadable: %s" % (a.config, exc))
    else:
        base = a.base_repo or ((info.get("cardData") or {}).get("base_model"))
        if isinstance(base, list):
            base = base[0] if base else None
        cfg, cfg_src = fetch_config(repo, base, token, a.no_network, notes)
    if cfg_src:
        notes.append("config.json read from %s" % cfg_src)
    kv = (kv_arithmetic(cfg, elem_bytes, elem_label, a.c_min) if cfg else
          {"lines": [], "bytes_per_token": None, "fixed_mib": 0.0,
           "notes": ["no config.json reached: KV bytes/token is UNKNOWN, so no "
                     "total below is a fit"]})
    board, reserve = budget(slug, notes)
    # "named" means the user picked files AND they resolved. When --quant was
    # given but resolved to nothing, the roster fallback below is informational
    # only: sizing DISK against all 26 files in the repo would report 415 GiB
    # "needed" and FAIL, and FIT would blame a quant nobody asked for. The
    # QUANTS failure is already the finding; a cascade of invented ones buries
    # it.
    cands = chosen or [g for g in (groups or []) if not g["mmproj"]]
    named = bool(a.quant) and bool(chosen)
    rows = check_fit(rep, cands, projector, kv, board, reserve, a.c_min, notes,
                     named, slug)
    check_disk(rep, slug, cands, projector, named)

    rep.render(out)
    out.write(rep.verdict() + "\n\n")
    if a.json:
        json.dump({"repo": repo, "slug": slug, "c_min": a.c_min,
                   "cache_type": a.cache_type,
                   "token_source": where if token else None,
                   "board_total_mib": board,
                   "desktop_reserve_max_mib": reserve,
                   "kv_bytes_per_token": kv.get("bytes_per_token"),
                   "fixed_state_mib": round(kv.get("fixed_mib", 0.0), 1),
                   "candidates": rows,
                   "checks": [{"name": r["name"], "status": r["status"],
                               "line": r["line"]} for r in rep.rows]},
                  out, indent=1)
        out.write("\n")
    return rep.exit_code()


if __name__ == "__main__":
    sys.exit(main())
