#!/usr/bin/env bash
set -euo pipefail

export PERL5LIB="$HOME/perl5/lib/perl5:$HOME/perl5/lib/perl5/darwin-thread-multi-2level${PERL5LIB:+:$PERL5LIB}"
exec /Library/TeX/texbin/latexindent "$@"
