#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'EOF'
Usage: ./tools/check-grammar.sh [options] [--] [file ...]

Run TeXtidote grammar/style checks on LaTeX files as an on-demand tool.

Options:
  --lang <code>       Language code for grammar checks (default: en)
  --firstlang <code>  First language code for false-friend checks
  --staged            Check only staged .tex files
  --all               Check all tracked target .tex files (default when no files given)
  --read-all          Pass --read-all to TeXtidote (useful for LaTeX fragments)
  --output <format>   TeXtidote output: plain|singleline|html|clickable (default: clickable)
  --color             Keep ANSI colors in output (default: disabled)
  -h, --help          Show this help text

Environment:
  TEXTIDOTE_CMD       Full command to run TeXtidote (overrides auto-detection)
  TEXTIDOTE_JAR       Path to textidote.jar (used when `textidote` is not in PATH)

Examples:
  ./tools/check-grammar.sh --staged
  ./tools/check-grammar.sh Chapter1.tex Chapter2.tex
  ./tools/check-grammar.sh --read-all --output clickable Titlepage.tex
  ./tools/check-grammar.sh --output clickable Titlepage.tex
  ./tools/check-grammar.sh --lang en --firstlang de --all
EOF
}

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

lang="en"
firstlang=""
selection_mode="all"
output_format="clickable"
read_all="false"
enable_color="false"
declare -a explicit_files=()

while [[ $# -gt 0 ]]; do
  case "$1" in
    --lang)
      if [[ $# -lt 2 ]]; then
        echo "Error: --lang requires a value." >&2
        usage
        exit 1
      fi
      lang="$2"
      shift 2
      ;;
    --firstlang)
      if [[ $# -lt 2 ]]; then
        echo "Error: --firstlang requires a value." >&2
        usage
        exit 1
      fi
      firstlang="$2"
      shift 2
      ;;
    --staged)
      selection_mode="staged"
      shift
      ;;
    --all)
      selection_mode="all"
      shift
      ;;
    --read-all)
      read_all="true"
      shift
      ;;
    --output)
      if [[ $# -lt 2 ]]; then
        echo "Error: --output requires a value." >&2
        usage
        exit 1
      fi
      output_format="$2"
      shift 2
      ;;
    --color)
      enable_color="true"
      shift
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    --)
      shift
      while [[ $# -gt 0 ]]; do
        explicit_files+=("$1")
        shift
      done
      ;;
    -*)
      echo "Error: unknown option '$1'." >&2
      usage
      exit 1
      ;;
    *)
      explicit_files+=("$1")
      shift
      ;;
  esac
done

case "$output_format" in
  plain|singleline|html|clickable) ;;
  *)
    echo "Error: unsupported output format '$output_format'." >&2
    exit 1
    ;;
esac

repo_root="$(git rev-parse --show-toplevel)"
cd "$repo_root"

declare -a candidate_files=()
if [[ ${#explicit_files[@]} -gt 0 ]]; then
  candidate_files=("${explicit_files[@]}")
elif [[ "$selection_mode" == "staged" ]]; then
  mapfile -t candidate_files < <(git diff --cached --name-only --diff-filter=ACMR -- '*.tex')
else
  mapfile -t candidate_files < <(git ls-files -- '*.tex')
fi

declare -a target_files=()
for file in "${candidate_files[@]}"; do
  if is_target_tex_file "$file"; then
    target_files+=("$file")
  fi
done

if [[ ${#target_files[@]} -eq 0 ]]; then
  echo "No target .tex files found for grammar checking."
  exit 0
fi

declare -a textidote_cmd=()
if [[ -n "${TEXTIDOTE_CMD:-}" ]]; then
  # shellcheck disable=SC2206
  textidote_cmd=(${TEXTIDOTE_CMD})
elif [[ -n "${TEXTIDOTE_JAR:-}" ]]; then
  textidote_cmd=(java -jar "$TEXTIDOTE_JAR")
elif [[ -f "$repo_root/tools/textidote.jar" ]]; then
  textidote_cmd=(java -jar "$repo_root/tools/textidote.jar")
elif [[ -n "$(find "$repo_root/textidote" -maxdepth 1 -type f -name 'textidote-*.jar' ! -name '*-sources.jar' ! -name '*-javadoc.jar' -print -quit 2>/dev/null)" ]]; then
  latest_textidote_jar="$(find "$repo_root/textidote" -maxdepth 1 -type f -name 'textidote-*.jar' ! -name '*-sources.jar' ! -name '*-javadoc.jar' | sort -V | tail -n 1)"
  textidote_cmd=(java -jar "$latest_textidote_jar")
elif command -v textidote >/dev/null 2>&1; then
  textidote_cmd=(textidote)
else
  cat >&2 <<'EOF'
Error: could not find TeXtidote.

Install `textidote` so it is in PATH, set TEXTIDOTE_JAR=/path/to/textidote.jar,
or set TEXTIDOTE_CMD='java -jar /path/to/textidote.jar'.
EOF
  exit 2
fi

declare -a args=(--check "$lang" --output "$output_format")
if [[ -n "$firstlang" ]]; then
  args+=(--firstlang "$firstlang")
fi
if [[ "$read_all" == "true" ]]; then
  args+=(--read-all)
fi
if [[ "$enable_color" != "true" ]]; then
  args+=(--no-color)
fi

echo "Running grammar checks on ${#target_files[@]} file(s)..."
"${textidote_cmd[@]}" "${args[@]}" "${target_files[@]}"
