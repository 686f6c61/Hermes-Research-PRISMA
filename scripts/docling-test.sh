#!/usr/bin/env bash
set -euo pipefail

# Validate structured PDF extraction against three materially different files:
# a two-column article, a table-heavy article, and an image-only scanned page.

source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/common.sh"

section "Prerequisites"
require_command docker
require_command python3
load_env

HERMES_CONTAINER="$(hermes_container_name)"
DOCLING_CONTAINER="${DOCLING_CONTAINER_NAME:-hermes-docling}"
WORKSPACE_DIR="$(resolve_package_path "${HERMES_WORKSPACE_DIR:-./runtime/workspace}")"

docker ps --format '{{.Names}}' | grep -qx "${HERMES_CONTAINER}" || \
  fail "${HERMES_CONTAINER} container is not running"

section "Start isolated Docling worker"
docker compose -f "${ROOT_DIR}/docker-compose.research.yml" --profile docling up -d docling

deadline=$((SECONDS + 360))
while [[ ${SECONDS} -lt ${deadline} ]]; do
  health_status="$(docker inspect "${DOCLING_CONTAINER}" --format '{{if .State.Health}}{{.State.Health.Status}}{{else}}{{.State.Status}}{{end}}' 2>/dev/null || true)"
  if [[ "${health_status}" == "healthy" ]]; then
    break
  fi
  if [[ "${health_status}" == "unhealthy" || "${health_status}" == "exited" ]]; then
    docker logs --tail 120 "${DOCLING_CONTAINER}" >&2 || true
    fail "Docling entered ${health_status} state"
  fi
  sleep 5
done

health_status="$(docker inspect "${DOCLING_CONTAINER}" --format '{{if .State.Health}}{{.State.Health.Status}}{{else}}{{.State.Status}}{{end}}' 2>/dev/null || true)"
[[ "${health_status}" == "healthy" ]] || fail "Docling did not become healthy before the timeout"
pass "Docling worker is healthy"

section "Create representative PDF fixtures"
timestamp="$(date +%Y%m%d%H%M%S)"
fixture_name=".hermes-docling-test-${timestamp}"
fixture_host="${WORKSPACE_DIR}/${fixture_name}"
fixture_container="/workspace/${fixture_name}"
mkdir -p "${fixture_host}/fulltext/pdf"

cat >"${fixture_host}/digital.tex" <<'TEX'
\documentclass[10pt,twocolumn]{article}
\usepackage[margin=18mm]{geometry}
\usepackage{graphicx}
\usepackage{lmodern}
\begin{document}
\title{Digital two-column evidence}
\author{Hermes Research Test}
\maketitle
\section{First finding}
DIGITAL TWO COLUMN MARKER. The left column introduces the research question
and states that evidence must preserve reading order.
\section{Second finding}
The right column reports a reproducible result and a bounded limitation.
\begin{figure}[h]
\centering
\includegraphics[width=.9\columnwidth]{evidence-flow.png}
\caption{Evidence flow used to validate source-picture extraction.}
\end{figure}
\end{document}
TEX

cat >"${fixture_host}/evidence-flow.svg" <<'SVG'
<svg xmlns="http://www.w3.org/2000/svg" width="900" height="420" viewBox="0 0 900 420">
  <rect width="900" height="420" fill="white"/>
  <g fill="none" stroke="black" stroke-width="8">
    <rect x="35" y="105" width="220" height="170"/>
    <rect x="340" y="105" width="220" height="170"/>
    <rect x="645" y="105" width="220" height="170"/>
    <path d="M255 190 H340 M560 190 H645"/>
  </g>
  <g fill="black" font-family="DejaVu Sans" font-size="34" text-anchor="middle">
    <text x="145" y="180">PDF</text>
    <text x="450" y="180">EVIDENCE</text>
    <text x="755" y="180">AUDIT</text>
  </g>
</svg>
SVG

cat >"${fixture_host}/tables.tex" <<'TEX'
\documentclass[11pt]{article}
\usepackage[margin=20mm]{geometry}
\usepackage{booktabs}
\usepackage{lmodern}
\begin{document}
\section*{Table-heavy evidence}
TABLE STRUCTURE MARKER.
\begin{table}[h]
\centering
\caption{Benchmark comparison}
\begin{tabular}{lrr}
\toprule
System & Accuracy & Latency \\
\midrule
Baseline & 71.2 & 18.4 \\
Proposed & 84.7 & 12.1 \\
\bottomrule
\end{tabular}
\end{table}
\end{document}
TEX

cat >"${fixture_host}/scan-source.tex" <<'TEX'
\documentclass[14pt]{article}
\usepackage[margin=18mm]{geometry}
\usepackage{lmodern}
\pagestyle{empty}
\begin{document}
\begin{center}
{\Huge\bfseries SCANNED EVIDENCE MARKER}\\[18mm]
{\Large This page has no reusable PDF text layer in the final fixture.}\\[8mm]
{\Large OCR must recover this scientific evidence correctly.}
\end{center}
\end{document}
TEX

docker exec "${HERMES_CONTAINER}" bash -c "
  set -euo pipefail
  cd '${fixture_container}'
  rsvg-convert -w 1800 -h 840 evidence-flow.svg -o evidence-flow.png
  latexmk -xelatex -interaction=nonstopmode -halt-on-error digital.tex >/tmp/docling-digital-latex.log
  latexmk -xelatex -interaction=nonstopmode -halt-on-error tables.tex >/tmp/docling-tables-latex.log
  latexmk -xelatex -interaction=nonstopmode -halt-on-error scan-source.tex >/tmp/docling-scan-source-latex.log
  cp digital.pdf fulltext/pdf/digital.pdf
  cp tables.pdf fulltext/pdf/tables.pdf
  pdftoppm -f 1 -l 1 -singlefile -r 220 -png scan-source.pdf scan-page >/tmp/docling-scan-render.log 2>&1
  cat >scan-wrapper.tex <<'TEX'
\\documentclass{article}
\\usepackage[paperwidth=210mm,paperheight=297mm,margin=0mm]{geometry}
\\usepackage{graphicx}
\\pagestyle{empty}
\\begin{document}
\\noindent\\includegraphics[width=\\paperwidth,height=\\paperheight]{scan-page.png}
\\end{document}
TEX
  latexmk -xelatex -interaction=nonstopmode -halt-on-error scan-wrapper.tex >/tmp/docling-scan-wrapper-latex.log
  cp scan-wrapper.pdf fulltext/pdf/scanned.pdf
"
pass "Digital, table-heavy, and scanned fixtures were created"

section "Run structured extraction"
DOCLING_SCRIPT="/opt/data/skills/research/prisma-systematic-review/scripts/docling_extract.py"
for fixture in \
  "digital.pdf|10.5555/hermes.digital.1" \
  "tables.pdf|10.5555/hermes.tables.2" \
  "scanned.pdf|10.5555/hermes.scan.3"
do
  pdf_name="${fixture%%|*}"
  doi="${fixture##*|}"
  docker exec \
    -e HERMES_DOCLING_ENABLED=1 \
    -e DOCLING_SERVE_URL=http://docling:5001 \
    -e HERMES_DOCLING_DOCUMENT_TIMEOUT="${HERMES_DOCLING_DOCUMENT_TIMEOUT:-180}" \
    "${HERMES_CONTAINER}" \
    python3 "${DOCLING_SCRIPT}" "${fixture_container}" \
      --pdf "${fixture_container}/fulltext/pdf/${pdf_name}" \
      --doi "${doi}" >/dev/null
done
pass "All three fixtures were processed"

section "Validate material evidence"
python3 - "${fixture_host}" <<'PY'
from pathlib import Path
import csv
import sys

root = Path(sys.argv[1])
manifest_path = root / "fulltext" / "docling" / "manifest.csv"
with manifest_path.open("r", encoding="utf-8", newline="") as handle:
    rows = list(csv.DictReader(handle))
if len(rows) != 3:
    raise SystemExit(f"Expected three manifest rows, found {len(rows)}")
if any(row["status"] != "success" for row in rows):
    raise SystemExit(f"Docling conversion failure: {rows}")

markdown = "\n".join(path.read_text(encoding="utf-8", errors="ignore") for path in (root / "fulltext" / "docling").glob("*.md")).upper()
if "DIGITAL TWO COLUMN MARKER" not in markdown:
    raise SystemExit("The two-column reading-order marker was not recovered")
if "SCANNED EVIDENCE MARKER" not in markdown:
    raise SystemExit("The image-only OCR marker was not recovered")

tables = list((root / "tables" / "source").glob("*.csv"))
if not tables:
    raise SystemExit("No source table was exported")
table_text = "\n".join(path.read_text(encoding="utf-8", errors="ignore") for path in tables)
if "Baseline" not in table_text or "84.7" not in table_text:
    raise SystemExit("The source table lost expected cells")
if "..." in table_text:
    raise SystemExit("A source table contains ellipsis instead of complete cells")

figures = list((root / "figures" / "source").glob("*"))
if not figures:
    raise SystemExit("No source figure was exported")
if any(path.stat().st_size < 4096 for path in figures):
    raise SystemExit("A source figure is unexpectedly small or empty")
PY
pass "Reading order, OCR, table cells, source figures, and DOI-only provenance passed"

if [[ "${KEEP_DOCLING_TEST_ARTIFACTS:-0}" == "1" ]]; then
  pass "Fixtures preserved at ${fixture_host}"
else
  rm -rf "${fixture_host}"
  pass "Temporary fixtures removed"
fi

printf '\nDocling integration test finished successfully.\n'
