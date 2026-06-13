# Thesis diff viewer

A tiny web app to render `git-latexdiff` between any two commits and view the
result in the browser — built for sharing changes with an advisor. Also renders
a plain (no-diff) PDF of any commit.

## Run locally

```bash
./difftool/serve.sh           # starts the server and opens the browser
# or
python3 difftool/server.py    # http://127.0.0.1:8765
python3 difftool/server.py --port 9000
```

No dependencies beyond what you already have: `python3`, `git-latexdiff`,
`latexmk`, `pdflatex` (all on PATH).

## Use

1. Pick a **Base** and a **Compare** commit (the dropdowns show date + commit
   subject).
2. **Generate diff** renders the latexdiff between them. **Full PDF** renders the
   Compare commit on its own, with no diff markup.
3. Builds run in the background (~30–70s for the full thesis); the card shows a
   spinner, then turns green. Click it to view the PDF inline. **Open ↗** opens a
   new tab; **Delete** removes it.

Added text is blue + underlined, removed text is red + struck through.

### Change index

When you view a diff, a **Changes** list appears beside the PDF: one entry per
change (⊕ added / ⊖ removed, with its page). Click an entry to jump the viewer
straight to it — no PDF-viewer panel needed.

How it works: `diff_bookmarks.py` (injected via git-latexdiff's `--filter`) hooks
latexdiff's change markers and writes a `\difchgmeta{n}{type}{abspage}{page}`
record into the `.aux` for each change; the server parses those and the UI jumps
the embedded viewer via `#page=`. (A PDF bookmark per change is also added as a
bonus for anyone who prefers the viewer's outline.)

Generated PDFs are cached in `build/diffs/` (gitignored), keyed by commit pair,
so re-viewing is instant and they survive a server restart.

## Deploy to Fly.io

The app is deployed at **https://alpaylan-thesis-diff.fly.dev** (public).

- `fly.toml` (repo root) — app config: port 8080, scale-to-zero, 2 GB RAM,
  `TZ=America/New_York` for timestamps.
- `Dockerfile` — full TeX Live + git + python3.
- `.dockerignore` (repo root) — trims the build context (keeps `.git` + figures).

The repo's git history is **baked into the image**, so the deployed viewer shows
commits as of build time.

### Auto-deploy on push

`.github/workflows/fly-deploy.yml` redeploys on every push to `main` (full
history via `fetch-depth: 0`). It needs the repo secret `FLY_API_TOKEN`
(a Fly deploy token). To manually deploy instead:

```bash
fly deploy --remote-only      # build on Fly's network (recommended)
```

> Local `fly deploy --local-only` pushes the ~5 GB image from your machine and
> can fail with `name unknown: app repository not found` when the registry token
> expires mid-upload. Prefer `--remote-only`.

Run a single machine (`fly scale count 1`): job state and the PDF cache live
per-machine, so multiple machines would serve inconsistently.

## How a diff is built

```bash
git latexdiff --main main.tex --latexmk \
    --build-dir build \      # latexmkrc sets $out_dir = 'build'
    --ln-untracked \         # pull in gitignored figure PDFs from the worktree
    --filter "python3 difftool/diff_bookmarks.py main.tex" \  # per-change bookmarks
    --ignore-latex-errors --no-view --quiet \
    -o build/diffs/diff_<old>_<new>.pdf  <old> <new>
```

A **full** build checks the commit out into a temporary `git worktree`, copies in
untracked figure PDFs, and runs `latexmk` (same engine as `build.sh`).

Builds are serialized (one at a time) so the machine isn't overloaded.
