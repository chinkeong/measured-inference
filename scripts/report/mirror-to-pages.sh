#!/usr/bin/env bash
# Mirror a finished report into the GitHub Pages working copy. COPY ONLY.
#
#   bash scripts/report/mirror-to-pages.sh <slug> <page-dir>
#   bash scripts/report/mirror-to-pages.sh qwen35-9b-family qwen-9b
#
# IT DOES NOT COMMIT AND IT DOES NOT PUSH, deliberately. Everything else in this
# tree pushes automatically because measured data is at risk on one disk (rule
# 28) and the remote is the author's own working repo. This target is DIFFERENT:
# it is a public website. Publishing is outward-facing and irreversible in the
# way that matters -- a wrong number on a public page is read, cached and cited
# before it can be corrected -- so the last step stays a human decision. The
# script stages the bytes and prints the two commands that would publish them.
#
# WHAT GETS MIRRORED. index.html plus the figures and images it references. The
# precedent in this repo is results/qwen38-27b-blind -> qwen-27b/, which carries
# index.html, figures/, a quant-ladder.png and the standalone agentic reports.
set -u
SLUG="${1:-}"
PAGE="${2:-}"
if [ -z "$SLUG" ] || [ -z "$PAGE" ]; then
    sed -n '2,20p' "$0" | sed 's/^# \{0,1\}//'
    exit 2
fi
REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
SRC="$REPO/results/$SLUG"
DEST="${PAGES_ROOT:-$HOME/Workspace/chinkeong.github.io}/$PAGE"

[ -d "$SRC" ] || { echo "no such campaign: $SRC"; exit 1; }
if [ ! -f "$SRC/index.html" ]; then
    echo "REFUSED: $SRC/index.html does not exist yet."
    echo "  Stage 7 writes it. There is nothing to publish before that."
    exit 1
fi
# A report that still says PROVISIONAL, TODO or PLACEHOLDER is not publishable,
# and the point of a check here is that the author is the last person who will
# notice their own placeholder.
if grep -qiE '\bTODO\b|\bPLACEHOLDER\b|\bFIXME\b|\bXXX\b' "$SRC/index.html"; then
    echo "REFUSED: index.html still contains TODO/PLACEHOLDER/FIXME/XXX:"
    grep -inE '\bTODO\b|\bPLACEHOLDER\b|\bFIXME\b|\bXXX\b' "$SRC/index.html" | head -5 | sed 's/^/    /'
    echo "  Fix those, or pass --force if they are legitimately part of the prose."
    [ "${3:-}" = "--force" ] || exit 1
fi

mkdir -p "$DEST"
cp -v "$SRC/index.html" "$DEST/index.html"
for extra in figures data/plots *.png; do
    if [ -e "$SRC/$extra" ]; then
        cp -rv "$SRC/$extra" "$DEST/" 2>/dev/null || true
    fi
done
echo
echo "mirrored -> $DEST"
echo "  $(du -sh "$DEST" | cut -f1) staged, $(find "$DEST" -type f | wc -l) file(s)"
echo
echo "NOT committed and NOT pushed. To publish, when you judge it ready:"
echo "  cd ${PAGES_ROOT:-$HOME/Workspace/chinkeong.github.io}"
echo "  git add $PAGE && git commit -m 'publish $SLUG' && git push origin master"
