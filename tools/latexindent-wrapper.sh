#!/usr/bin/env bash
set -euo pipefail

export PERL5LIB="$HOME/perl5/lib/perl5:$HOME/perl5/lib/perl5/darwin-thread-multi-2level${PERL5LIB:+:$PERL5LIB}"

for arg in "$@"; do
  case "$arg" in
    -l|--local|--local=*)
      exec /Library/TeX/texbin/latexindent "$@"
      ;;
  esac
done

exec /Library/TeX/texbin/latexindent -l "$@"
