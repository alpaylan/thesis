#!/usr/bin/env bash
set -euo pipefail

is_target_tex_file() {
  local path="$1"
  case "$path" in
    styles/*|bib/*|build/*|font_variants/*|tools/*|macros/*)
      return 1
      ;;
    *.tex)
      return 0
      ;;
    *)
      return 1
      ;;
  esac
}

mapfile -t staged_tex_files < <(git diff --cached --name-only --diff-filter=ACMR -- '*.tex')
if [[ ${#staged_tex_files[@]} -eq 0 ]]; then
  exit 0
fi

violations=()
for file in "${staged_tex_files[@]}"; do
  if ! is_target_tex_file "$file"; then
    continue
  fi

  file_violations="$(
    git diff --cached --unified=0 -- "$file" | awk -v file="$file" '
      /^@@/ {
        hunk = $0
        sub(/^.*\+/, "", hunk)
        sub(/ .*/, "", hunk)
        split(hunk, parts, ",")
        line_no = parts[1] - 1
        next
      }
      /^\+\+\+/ { next }
      /^\+/ {
        line_no++
        text = substr($0, 2)
        if (index(text, "\"") > 0) {
          printf "%s:%d:%s\n", file, line_no, text
        }
        next
      }
    '
  )" || {
    echo "pre-commit: failed to parse staged diff for $file" >&2
    exit 2
  }

  while IFS= read -r violation; do
    if [[ -n "$violation" ]]; then
      violations+=("$violation")
    fi
  done <<< "$file_violations"
done

if [[ ${#violations[@]} -gt 0 ]]; then
  echo 'pre-commit: straight double quote (") detected in staged prose .tex lines.'
  echo "Use LaTeX quotes: \`\`like this''"
  echo
  printf '%s\n' "${violations[@]}"
  echo
  echo 'If this is intentional, edit the line before committing.'
  exit 1
fi
