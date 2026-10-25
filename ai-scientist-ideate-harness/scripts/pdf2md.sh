#!/usr/bin/env bash
# Convert <research_dir>/pdfs/*.pdf -> <research_dir>/step5_full_text/*.md via the pdf2md (marker-pdf) service.
# Credentials come from mcp/scholar_mcp/.env (gitignored) so the API key never appears on a command line.
#   bash pdf2md.sh <research_dir> [per_paper_timeout_seconds=900]
#
# The service converts one paper at a time and a single stuck job blocks everything queued behind it (one job was
# observed "running" for 59 minutes). So each paper gets a time limit, and whatever is still unconverted at the end is
# converted with pdftotext instead - lower quality, but the pipeline never waits on a dead job. fulltext-status then
# labels those files `full-text-plain`.
# Exit 3 = PDF2MD_API_KEY not configured (pdftotext fallback is still applied).
set -uo pipefail
RD="${1:?usage: pdf2md.sh <research_dir> [per_paper_timeout_seconds]}"
LIMIT="${2:-900}"
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ENV_FILE="$HERE/mcp/scholar_mcp/.env"
if [[ -f "$ENV_FILE" ]]; then set -a; . "$ENV_FILE"; set +a; fi
[[ -d "$RD/pdfs" ]] || { echo "pdf2md: $RD/pdfs not found" >&2; exit 1; }
PY="${IDEATE_PYTHON:-python3}"
OUT="$RD/step5_full_text"; mkdir -p "$OUT"
rc=0
if [[ -z "${PDF2MD_API_KEY:-}" ]]; then
  echo "pdf2md: PDF2MD_API_KEY not set (looked in $ENV_FILE) - using pdftotext for everything" >&2; rc=3
else
  # One PDF per client call, so this script can see each outcome. The service is strictly sequential: a job submitted
  # after a stuck one just queues behind it and times out too. Two timeouts in a row therefore mean the service is
  # wedged, and the rest of the batch goes straight to pdftotext instead of waiting LIMIT seconds per paper.
  strikes=0
  for pdf in "$RD"/pdfs/*.pdf; do
    [[ -e "$pdf" ]] || continue
    key="$(basename "$pdf" .pdf)"
    [[ -s "$OUT/$key.md" ]] && continue
    if (( strikes >= 2 )); then break; fi
    # Figures go to the shared step5_full_text/figure/ as <key>_<name>; `ideate_tools.py figures` indexes them and adds
    # whole-page renders for every paper, including the ones pdf2md never converts.
    if "$PY" "$HERE/mcp/pdf2md_client.py" "$pdf" -o "$OUT" --figures-dir "$OUT/figure" --timeout "$LIMIT" && [[ -s "$OUT/$key.md" ]]; then
      strikes=0
    else
      strikes=$((strikes+1)); echo "pdf2md: $key failed or gave no result within the ${LIMIT}s polling limit (plus upload time; consecutive failures: $strikes)" >&2
    fi
  done
  (( strikes >= 2 )) && echo "pdf2md: service looks wedged (2 consecutive failures) - remaining papers use pdftotext" >&2
fi
fallback=0; failed=0
for pdf in "$RD"/pdfs/*.pdf; do
  [[ -e "$pdf" ]] || continue
  key="$(basename "$pdf" .pdf)"
  [[ -s "$OUT/$key.md" ]] && continue
  # No -layout: that flag keeps the physical page layout, which on a two-column paper splices the left and right
  # columns together line by line ("...some improvements    al. [27] introduced..."). The default mode reads each
  # column in order. Tables are lost either way.
  if command -v pdftotext >/dev/null 2>&1 && pdftotext -enc UTF-8 "$pdf" "$OUT/$key.md" 2>/dev/null && [[ -s "$OUT/$key.md" ]]; then
    fallback=$((fallback+1)); echo "pdf2md: $key -> pdftotext fallback"
  else
    rm -f "$OUT/$key.md"; failed=$((failed+1)); echo "pdf2md: $key -> could not be converted (stays pdf-only)" >&2
  fi
done
echo "pdf2md: done - $(ls "$OUT"/*_meta.json 2>/dev/null | wc -l | tr -d ' ') via pdf2md, $fallback via pdftotext, $failed unconverted"
echo "pdf2md: next - ideate_tools.py figures <research_dir> (page images for every PDF), then fulltext-status"
exit $rc
