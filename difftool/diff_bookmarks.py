#!/usr/bin/env python3
"""git-latexdiff --filter hook: inject a PDF bookmark at every change.

git-latexdiff runs this inside the diff checkout with the flattened diff file
as the only argument; it must rewrite that file in place.

We add a small preamble block (just before \\begin{document}) that hooks
latexdiff's own \\DIFaddbegin / \\DIFdelbegin markers so each change drops a
top-level PDF bookmark "Change N (p. X)".  The thesis already loads hyperref,
so the bookmarks show up as a clickable outline/index in any PDF viewer.
"""

import sys

INJECT = r"""
% --- diff-viewer: per-change PDF bookmarks (injected) -----------------------
% latexdiff defines \DIFaddbegin / \DIFdelbegin with \DeclareRobustCommand, so
% we patch them with etoolbox's \pretocmd (which handles robust commands) to
% drop a top-level PDF bookmark at the start of every change.
\usepackage{etoolbox}
\newcounter{difchg}
\newcommand{\difchgmark}{%
  \ifmmode\else
    \stepcounter{difchg}%
    \pdfbookmark[0]{Change \thedifchg\space(p.\thepage)}{difchg.\arabic{difchg}}%
  \fi}
\AtBeginDocument{%
  \ifdef{\DIFaddbegin}{\pretocmd{\DIFaddbegin}{\difchgmark}{}{}}{}%
  \ifdef{\DIFdelbegin}{\pretocmd{\DIFdelbegin}{\difchgmark}{}{}}{}%
}
% --- end diff-viewer block --------------------------------------------------
"""


def main() -> int:
    if len(sys.argv) < 2:
        return 0
    path = sys.argv[1]
    with open(path, encoding="utf-8") as fh:
        text = fh.read()

    if "difchgmark" in text:           # already injected
        return 0
    marker = r"\begin{document}"
    idx = text.find(marker)
    if idx == -1:                      # no preamble boundary found; leave as-is
        return 0
    text = text[:idx] + INJECT + "\n" + text[idx:]

    with open(path, "w", encoding="utf-8") as fh:
        fh.write(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
