#!/usr/bin/env python3
"""Fail when an ignore rule swallows an instrument or a primary record.

    python scripts/verify/instrument-guard.py            # from the repo root
    python scripts/verify/instrument-guard.py --site DIR # also audit a published copy
    python scripts/verify/instrument-guard.py --strict   # dangling names fail too

WHY THIS EXISTS. Two incidents on 2026-08-27, found by accident within hours
of each other, both the same shape: AN IGNORE RULE WRITTEN FOR BULK OUTPUT
QUIETLY SWALLOWED THE INSTRUMENT THAT PRODUCED IT.

1. THE CHART WITH NO RENDERER. The quant-ladder PNG published as the page's
   own preview image existed nowhere in the project tree as source. Its
   generator, make-ladder-png.py, survived only inside a session temporary
   directory and was recovered by matching an md5 against the committed image.
   One reboot, or one temp sweep, and a published chart would have had no way
   to be redrawn - not a lost convenience, but a published claim that could
   never again be corrected, re-scaled, or defended.

2. THE WORKING DIRECTORY THAT WAS NOT WORKING DATA. .gitignore carried
   results/**/work/ under the comment "campaign working data". That directory
   in fact held judge.py, the six rule21-*.py suite scripts, power-integrate.py,
   lib.ps1 - the shared harness every phase ran through - and
   followup-measurements.md, whose numbers appear on the published page in four
   places. Thirty-one files under it had been force-added one at a time by
   whoever happened to notice; eleven had not. Nothing ever told anyone which
   was which.

Neither incident announced itself. Both were survivable only because someone
happened to look. The point of this script is that nobody has to look again:
it makes the failure mode loud at the moment it is introduced, rather than
silent until the machine is rebuilt.

WHAT IT CHECKS. Four questions, each one a way the two incidents can recur:

  A. DANGLING CITATION. A tracked file names another file - by path, or by a
     distinctive basename - and that file exists on disk but git does not have
     it. This is incident 2 exactly: a committed record citing an instrument
     that is not committed.

  B. UNTRACKED INPUT OF A TRACKED SCRIPT. A tracked .py / .ps1 / .bat opens a
     data file git does not have. Committing an instrument without its input
     does not restore reproducibility; the script still cannot run on a fresh
     clone. The rescue of power-integrate.py left both of its inputs outside
     git, and that is the case this check is calibrated on.

  C. PUBLISHED FIGURE WITH NO TRACKED GENERATOR. An image that is published or
     committed and that no tracked file so much as names is incident 1: a
     picture nothing in the repository knows how to draw.

  D. UNTRACKED RECORD IN A DIRECTORY A TRACKED SCRIPT READS. Check B can only
     see filenames that are written down. archdata.py builds its filenames -
     "%s-%s.csv" % (tag, kind) - so no literal in the repository ever spells
     iq4xs-agentic-dmon.csv, and yet that one CSV is the sole source of nine
     published figures. Check D therefore follows the DIRECTORY constant
     instead: if a tracked instrument points at a data root, every record in
     that root is an input, named or not.

WHAT IT DELIBERATELY DOES NOT CHECK. Model weights, downloaded runtimes,
benchmark corpora, per-run transcripts and byte caches are re-creatable by
design and their ignore rules are correct. They become findings here only if a
tracked file cites one BY NAME - at which point the file is no longer bulk, it
is evidence somebody leaned on.

THE ESCAPE HATCH, AND WHY IT IS NARROW. A genuinely re-creatable file that
trips a check goes in scripts/verify/instrument-guard-allow.txt, one path per
line, each with a written reason after a '#'. A line with no reason is itself
an error. Silencing this script costs one sentence saying how the file would
be regenerated; if that sentence is hard to write, the file belongs in git.

EXIT STATUS. 0 when nothing is swallowed. 1 when something is - and the output
names the file to add, the tracked file that depends on it, and the ignore
rule that hid it, so a reader can act without re-deriving the analysis.
"""
import argparse
import collections
import os
import re
import subprocess
import sys

# ---------------------------------------------------------------------------
# What counts as a file worth naming. Extensions of instruments and of primary
# records - not of bulk. A .log or a .dat is bulk UNTIL a tracked file cites
# it, and citation is check A, which does not care about the extension.
INSTRUMENT_EXT = {".py", ".ps1", ".bat", ".sh", ".psm1"}
RECORD_EXT = {".json", ".jsonl", ".csv", ".tsv", ".txt", ".md", ".yaml", ".yml"}
FIGURE_EXT = {".png", ".svg", ".webp", ".jpg", ".jpeg", ".pdf"}
CITED_EXT = INSTRUMENT_EXT | RECORD_EXT | FIGURE_EXT | {".html", ".log", ".dat", ".err"}

# Files whose text is read looking for citations.
TEXTY_EXT = INSTRUMENT_EXT | {".md", ".html", ".json", ".txt", ".yaml", ".yml"}

SKIP_DIRS = {".git", "__pycache__", ".venv", "node_modules", "models", "bin"}

# A basename must look deliberate before a bare mention of it counts as a
# citation. "index.html" and "config.json" are said everywhere and name
# nothing; "followup-m2b.ps1" and "iq4xs-agentic-dmon.csv" name one object.
GENERIC_NAMES = {
    "index.html", "readme.md", "config.json", "setup.py", "main.py",
    "package.json", "requirements.txt", "notes.md", "results.json",
    "output.json", "data.json", "test.py", "__init__.py", "makefile",
}


def norm(p):
    p = p.replace("\\", "/")
    while p.startswith("./"):
        p = p[2:]
    return p


def git(repo, *args):
    return subprocess.run(["git", "-C", repo] + list(args),
                          capture_output=True, text=True).stdout


def repo_root():
    top = subprocess.run(["git", "rev-parse", "--show-toplevel"],
                         capture_output=True, text=True).stdout.strip()
    if not top:
        sys.exit("instrument-guard: not inside a git repository")
    return os.path.abspath(top)


def unquote_path(p):
    """git C-quotes a pathname that contains anything unusual."""
    if len(p) >= 2 and p[0] == '"' and p[-1] == '"':
        try:
            return p[1:-1].encode().decode("unicode_escape")
        except Exception:
            return p[1:-1]
    return p


def read(path):
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as fh:
            return fh.read()
    except OSError:
        return ""


# ---------------------------------------------------------------------------
class Index:
    """Everything on disk, everything git has, and the rule that explains the
    difference. One walk and one batched check-ignore, so a large tree stays
    cheap enough to run in a pre-commit hook."""

    def __init__(self, repo):
        self.repo = repo
        self.tracked = {norm(p) for p in git(repo, "ls-files").splitlines() if p}
        self.disk = []
        for dirpath, dirnames, filenames in os.walk(repo):
            dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
            for fn in filenames:
                self.disk.append(
                    norm(os.path.relpath(os.path.join(dirpath, fn), repo)))
        self.diskset = set(self.disk)
        self.by_base = collections.defaultdict(list)
        for rel in self.disk:
            self.by_base[os.path.basename(rel).lower()].append(rel)
        self.untracked = [p for p in self.disk if p not in self.tracked]
        self.rules = self._ignore_rules(self.untracked)

    def _ignore_rules(self, paths):
        """git check-ignore -v, batched. path -> 'sourcefile:line:pattern'.

        The bytes matter here. Feeding this text-mode on Windows translates
        every "\\n" into "\\r\\n", git then reads a carriage return as part of
        the PATH, quotes it back as "path\\r", nothing matches, and the whole
        check silently reports every ignored file as merely untracked - a
        success-shaped failure of exactly the kind this repository refuses to
        ship. Send bytes, decode the answer, and unquote what git quoted."""
        rules = {}
        for i in range(0, len(paths), 400):
            chunk = paths[i:i + 400]
            out = subprocess.run(
                ["git", "-C", self.repo, "check-ignore", "-v", "--stdin"],
                input="\n".join(chunk).encode("utf-8"),
                capture_output=True).stdout.decode("utf-8", "replace")
            for line in out.splitlines():
                parts = line.rstrip("\r").split("\t")
                if len(parts) == 2:
                    rules[norm(unquote_path(parts[1]))] = parts[0]
        return rules

    def status(self, rel):
        if rel in self.tracked:
            return "tracked", ""
        if rel not in self.diskset:
            return "missing", ""
        rule = self.rules.get(rel)
        return ("ignored", rule) if rule else ("untracked", "")

    def resolve(self, token, near=None):
        """Turn a written reference into a repo-relative path, or None.

        Three ways a file gets named in this repository, in falling order of
        confidence: a repo-relative path, a path relative to the citing file,
        and a bare basename that is unique on disk."""
        t = norm(token).lstrip("/")
        t = re.sub(r"^(?:\.\./)+", "", t)
        if not t:
            return None
        if t in self.diskset:
            return t
        if near:
            cand = norm(os.path.normpath(
                os.path.join(os.path.dirname(near), t)))
            if cand in self.diskset:
                return cand
        base = os.path.basename(t).lower()
        if "/" in t:
            # Partial path, or an absolute one written into a log with a drive
            # letter the reader no longer has. Strip leading components until
            # something matches; the longest surviving suffix wins.
            hits = [p for p in self.by_base.get(base, [])
                    if p.lower().endswith("/" + t.lower())]
            if len(hits) == 1:
                return hits[0]
            parts = t.split("/")
            for i in range(1, len(parts)):
                tail = "/".join(parts[i:])
                if tail in self.diskset:
                    return tail
                hits = [p for p in self.by_base.get(base, [])
                        if p.lower().endswith("/" + tail.lower())]
                if len(hits) == 1:
                    return hits[0]
            return None
        if base in GENERIC_NAMES:
            return None
        if not re.search(r"[-_0-9]", base):          # not distinctive enough
            return None
        hits = self.by_base.get(base, [])
        return hits[0] if len(hits) == 1 else None


    def resolve_dir(self, token, near=None):
        """Same as resolve(), for a directory rather than a file."""
        t = norm(token).lstrip("/")
        t = re.sub(r"^(?:\.\./)+", "", t)
        cands = [t]
        if near:
            cands.append(norm(os.path.normpath(
                os.path.join(os.path.dirname(near), t))))
        parts = t.split("/")
        cands += ["/".join(parts[i:]) for i in range(1, len(parts))]
        for c in cands:
            if c and os.path.isdir(os.path.join(self.repo, c)):
                return c
        return None


EXT_ALT = "|".join(sorted(e[1:] for e in CITED_EXT))
# A path-ish or name-ish token ending in an extension worth caring about.
TOKEN_RE = re.compile(
    r"(?<![A-Za-z0-9])((?:[\w.\-]+[\\/])*[\w.\-]+\.(?:" + EXT_ALT + r"))"
    r"(?![A-Za-z0-9])", re.IGNORECASE)

# A token whose first segment is a hostname is a link, not a file here.
URLISH = re.compile(
    r"^(?:https?:)?[\w.\-]+\.(?:com|org|net|io|dev|ai|gov|edu|co|me)(?:/|$)",
    re.IGNORECASE)

JOIN_RE = re.compile(r"(?:os\.path\.)?join[ \t]*\(([^()]*)\)", re.IGNORECASE)
STR_RE = re.compile(r"""['"]([^'"\n]{1,200})['"]""")
ENDS_RE = re.compile(r"\.(" + EXT_ALT + r")$", re.IGNORECASE)


def citations(text):
    """Every file-shaped token in a text, with the line it sits on."""
    for n, line in enumerate(text.splitlines(), 1):
        for m in TOKEN_RE.finditer(line):
            yield n, m.group(1)


def declared_inputs(text):
    """Paths a script names in code. os.path.join / Join-Path chains are
    reassembled, so join(QL, "qat-q2_0", "ppl.json") resolves to the right
    rung rather than to whichever ppl.json was walked first."""
    found = []
    for n, line in enumerate(text.splitlines(), 1):
        for m in JOIN_RE.finditer(line):
            parts = STR_RE.findall(m.group(1))
            if parts and ENDS_RE.search(parts[-1]):
                found.append((n, "/".join(p.strip("\\/") for p in parts)))
        for m in STR_RE.finditer(line):
            s = m.group(1)
            if ENDS_RE.search(s):
                s = re.sub(r"^.*[$}]", "", s)     # drop "$DATA\", "${x}/" heads
                s = s.lstrip("\\/")
                if s:
                    found.append((n, s))
    return found


# Path components that only ever name a data root, never a source tree. A
# directory constant that ends in one of these is what check D follows.
DATA_ROOTS = ("data", "telemetry", "power", "register", "rule21", "followup",
              "quant-ladder", "overnight", "power-matrix", "judge", "figures",
              "results")


def declared_dirs(text):
    """DIRECTORY constants a script points at, e.g.

        TEL = os.path.join(ROOT, "results", "qwen38-27b-blind", "data",
                           "telemetry")

    This is the check that catches an input whose FILENAME is computed rather
    than written down. archdata.py builds "%s-%s.csv" % (tag, kind) at call
    time, so no literal in the file ever says iq4xs-agentic-dmon.csv - and yet
    that CSV is the sole source of nine published figures. A guard that only
    reads string literals would miss the single largest hole in the tree."""
    out = []
    for n, line in enumerate(text.splitlines(), 1):
        for m in JOIN_RE.finditer(line):
            parts = [p.strip("\\/") for p in STR_RE.findall(m.group(1))]
            parts = [p for p in parts if p and not ENDS_RE.search(p)]
            if len(parts) >= 2 and parts[-1].lower() in DATA_ROOTS:
                out.append((n, "/".join(parts)))
    return out


def allowed(rel, allow):
    """A path is allowed by an exact path, by a bare basename, or by a
    directory prefix written with a trailing slash."""
    if rel in allow or os.path.basename(rel) in allow:
        return True
    return any(a.endswith("/") and rel.startswith(a) for a in allow)


def load_allow(repo):
    path = os.path.join(repo, "scripts", "verify", "instrument-guard-allow.txt")
    allow, bad = {}, []
    if not os.path.exists(path):
        return allow, bad
    for n, line in enumerate(read(path).splitlines(), 1):
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        p, _, reason = line.partition("#")
        p = norm(p.strip())
        if not p:
            continue
        if not reason.strip():
            bad.append((n, p))
        allow[p] = reason.strip()
    return allow, bad


class Findings:
    def __init__(self):
        self.items = collections.OrderedDict()

    def add(self, check, path, status, rule, why):
        it = self.items.setdefault(path, {"status": status, "rule": rule,
                                          "why": collections.OrderedDict()})
        seen = it["why"].setdefault(check, [])
        if why not in seen:
            seen.append(why)

    def __len__(self):
        return len(self.items)


# ---------------------------------------------------------------------------
def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--site", action="append", default=[],
                    help="directory holding a published copy, audited for "
                         "figures with no tracked generator (repeatable)")
    ap.add_argument("--strict", action="store_true",
                    help="also fail when a tracked file names a path that is "
                         "nowhere on disk")
    ap.add_argument("--quiet-ok", action="store_true",
                    help="print nothing when the repository is clean")
    args = ap.parse_args()

    repo = repo_root()
    idx = Index(repo)
    allow, bad_allow = load_allow(repo)

    fail = Findings()
    dangling = []
    nogen = []

    tracked_text = [p for p in sorted(idx.tracked)
                    if os.path.splitext(p)[1].lower() in TEXTY_EXT]
    blobs = {p: read(os.path.join(repo, p)) for p in tracked_text}

    # -- A. a tracked file names a file git does not have --------------------
    for citer, text in blobs.items():
        for line, token in citations(text):
            rel = idx.resolve(token, near=citer)
            if rel is None:
                if ("/" in token or "\\" in token) and not URLISH.match(token):
                    dangling.append((citer, line, token))
                continue
            if rel == citer or allowed(rel, allow):
                continue
            st, rule = idx.status(rel)
            if st in ("ignored", "untracked"):
                fail.add("A", rel, st, rule, f"{citer}:{line}")

    # -- B. a tracked script's own declared inputs --------------------------
    for script in sorted(idx.tracked):
        if os.path.splitext(script)[1].lower() not in INSTRUMENT_EXT:
            continue
        text = blobs.get(script) or read(os.path.join(repo, script))
        for line, token in declared_inputs(text):
            rel = idx.resolve(token, near=script)
            if rel is None or rel == script:
                continue
            if allowed(rel, allow):
                continue
            st, rule = idx.status(rel)
            if st in ("ignored", "untracked"):
                fail.add("B", rel, st, rule, f"{script}:{line}")

    # -- D. every record inside a directory a tracked script reads ----------
    dirs_by_dir = {}
    for script in sorted(idx.tracked):
        if os.path.splitext(script)[1].lower() not in INSTRUMENT_EXT:
            continue
        text = blobs.get(script) or read(os.path.join(repo, script))
        for line, token in declared_dirs(text):
            d = idx.resolve_dir(token, near=script)
            if d and d.count("/") >= 1:          # never a whole top-level tree
                dirs_by_dir.setdefault(d, f"{script}:{line}")
    for d, cite in sorted(dirs_by_dir.items()):
        if allowed(d + "/x", allow):
            continue
        for rel in idx.disk:
            if not rel.startswith(d + "/"):
                continue
            if os.path.splitext(rel)[1].lower() not in (RECORD_EXT | INSTRUMENT_EXT):
                continue
            if allowed(rel, allow):
                continue
            st, rule = idx.status(rel)
            if st in ("ignored", "untracked"):
                fail.add("D", rel, st, rule,
                         f"{cite} reads the directory {d}/")

    # -- C. a published or committed figure with no tracked generator -------
    figures = []
    for rel in idx.disk:
        if os.path.splitext(rel)[1].lower() in FIGURE_EXT and "/figures/" in rel:
            figures.append((rel, os.path.join(repo, rel), "committed", True))
    for site in args.site:
        if not os.path.isdir(site):
            print(f"note: --site {site} is not a directory here; skipped")
            continue
        for dirpath, dirnames, filenames in os.walk(site):
            dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
            for fn in filenames:
                if os.path.splitext(fn)[1].lower() in FIGURE_EXT:
                    full = os.path.join(dirpath, fn)
                    figures.append((norm(os.path.relpath(full, site)), full,
                                    f"published under {norm(site)}", False))

    gen_text = {p: (blobs.get(p) or read(os.path.join(repo, p))).lower()
                for p in idx.tracked
                if os.path.splitext(p)[1].lower() in (INSTRUMENT_EXT | {".json"})}

    for figrel, figfull, where, in_repo in figures:
        base = os.path.basename(figrel)
        if allowed(figrel, allow) or base in allow:
            continue
        if not any(base.lower() in t for t in gen_text.values()):
            nogen.append((figrel, where))
        if in_repo:
            rel = norm(os.path.relpath(figfull, repo))
            st, rule = idx.status(rel)
            if st in ("ignored", "untracked"):
                fail.add("C", rel, st, rule,
                         "a figure under figures/ that git does not have")

    # -- report -------------------------------------------------------------
    W = 78
    clean = not (len(fail) or nogen or bad_allow or (args.strict and dangling))
    if clean and args.quiet_ok:
        return 0

    print("=" * W)
    print("INSTRUMENT GUARD - does anything published lean on a file git does "
          "not have?")
    print("=" * W)
    print(f"repo            {repo}")
    print(f"tracked files   {len(idx.tracked)}")
    print(f"on disk         {len(idx.disk)}   "
          f"({len(idx.untracked)} untracked, {len(idx.rules)} of those ignored "
          f"by a rule)")
    print(f"allow-listed    {len(allow)}")
    print()

    if bad_allow:
        print("ALLOW-LIST ENTRIES WITH NO WRITTEN REASON - a reason is required:")
        for n, p in bad_allow:
            print(f"  scripts/verify/instrument-guard-allow.txt:{n}   {p}")
        print()

    if len(fail):
        order = {"A": 0, "B": 1, "D": 2, "C": 3}
        rows = sorted(fail.items.items(),
                      key=lambda kv: (min(order[c] for c in kv[1]["why"]),
                                      kv[0]))
        print(f"{len(rows)} FILE(S) THAT SOMETHING TRACKED DEPENDS ON, AND GIT "
              "DOES NOT HAVE")
        print("-" * W)
        for path, info in rows:
            full = os.path.join(repo, path)
            size = (f"   {os.path.getsize(full):,} bytes"
                    if os.path.exists(full) else "")
            print()
            print(f"  {path}{size}")
            print(f"      status    {info['status']}"
                  + (f", by rule {info['rule']}" if info["rule"] else ""))
            for check, whys in info["why"].items():
                label = {"A": "cited by", "B": "read by ", "D": "inside  ",
                         "C": "figure  "}[check]
                for w in whys[:4]:
                    print(f"      {label}  {w}")
                if len(whys) > 4:
                    print(f"      {' ' * len(label)}  ...and "
                          f"{len(whys) - 4} more")
            print(f"      fix       git add -f {path}")
        print()

    if nogen:
        print(f"{len(nogen)} PUBLISHED OR COMMITTED FIGURE(S) WITH NO TRACKED "
              "GENERATOR")
        print("-" * W)
        print("  No tracked script or manifest so much as names these files, so")
        print("  nothing in this repository knows how to redraw them.")
        for figrel, where in nogen:
            print(f"    {figrel}    ({where})")
        print("  fix       commit the script that draws it, or allow-list the")
        print("            file with a written reason it needs no generator.")
        print()

    if dangling:
        head = "NAMED BUT NOWHERE ON DISK"
        print(f"{head}{'' if args.strict else ' (warning only)'}: "
              f"{len(dangling)} reference(s)")
        print("-" * W)
        for citer, line, token in dangling[:25]:
            print(f"    {citer}:{line}  ->  {token}")
        if len(dangling) > 25:
            print(f"    ...and {len(dangling) - 25} more")
        print()

    if clean:
        print("OK. Every file that something tracked depends on is tracked.")
        return 0
    print("=" * W)
    print("FAIL. Each line above is a published or committed claim that is one")
    print("disk wipe away from being unreproducible. Add the file, or write in")
    print("instrument-guard-allow.txt how it would be remade.")
    print("=" * W)
    return 1


if __name__ == "__main__":
    sys.exit(main())
