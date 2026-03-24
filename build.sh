#!/usr/bin/env bash
set -euo pipefail

latexmk -pdf -interaction=nonstopmode main.tex
# Keep the PDF and remove intermediary files.
latexmk -c main.tex
find build -type f ! -name 'main.pdf' -delete
# Remove any LaTeX artifacts that some packages/tools may emit in project root.
rm -f ./*.aux ./main.fdb_latexmk ./main.fls ./main.lof ./main.log ./main.lot ./main.out ./main.pdf ./main.synctex.gz ./main.toc
