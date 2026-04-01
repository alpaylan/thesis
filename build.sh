#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'EOF'
Usage: ./build.sh [--font times|tgpagella|mathpazo]

Build the thesis PDF into build/main.pdf.
Defaults to --font times when omitted.
EOF
}

font="times"
while [[ $# -gt 0 ]]; do
  case "$1" in
    --font)
      if [[ $# -lt 2 ]]; then
        echo "Error: --font requires a value." >&2
        usage
        exit 1
      fi
      font="$2"
      shift 2
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "Error: unknown argument '$1'." >&2
      usage
      exit 1
      ;;
  esac
done

case "$font" in
  times)
    tex_source="main.tex"
    ;;
  tgpagella)
    tex_source="font_variants/main_tgpagella.tex"
    ;;
  mathpazo)
    tex_source="font_variants/main_mathpazo.tex"
    ;;
  *)
    echo "Error: unsupported font '$font'. Use times, tgpagella, or mathpazo." >&2
    exit 1
    ;;
esac

if [[ ! -f "$tex_source" ]]; then
  echo "Error: missing source file '$tex_source'." >&2
  exit 1
fi

rm -f build/main.pdf

build_jobname="main-build-temp"
build_output_pdf="build/${build_jobname}.pdf"

latexmk_args=(-pdf -interaction=nonstopmode -jobname="$build_jobname" "$tex_source")
if [[ "$font" == "tgpagella" ]]; then
  # tgpagella variant currently emits a known package conflict but still produces PDF.
  set +e
  latexmk -f "${latexmk_args[@]}"
  rc=$?
  set -e
  if [[ $rc -ne 0 && ! -f "$build_output_pdf" ]]; then
    exit "$rc"
  fi
else
  latexmk "${latexmk_args[@]}"
fi

if [[ ! -f "$build_output_pdf" ]]; then
  echo "Error: build did not produce '$build_output_pdf'." >&2
  exit 1
fi
cp "$build_output_pdf" build/main.pdf

# Keep the PDF and remove intermediary files.
latexmk -c -jobname="$build_jobname" "$tex_source"
find build -type f ! -name 'main.pdf' -delete
# Remove any LaTeX artifacts that some packages/tools may emit in project root.
rm -f ./*.aux ./main.fdb_latexmk ./main.fls ./main.lof ./main.log ./main.lot ./main.out ./main.pdf ./main.synctex.gz ./main.toc

echo "Built build/main.pdf with font '$font'."
