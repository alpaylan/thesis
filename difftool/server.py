#!/usr/bin/env python3
"""Tiny web UI to render git-latexdiff PDFs between two commits.

Run it from the repo root (or anywhere):

    python3 difftool/server.py            # serves on http://127.0.0.1:8765
    python3 difftool/server.py --port 9000
    python3 difftool/server.py --main main.tex

No third-party dependencies. Generated PDFs are cached in build/diffs/.

Two kinds of build:
  * diff  — git-latexdiff between two commits (with per-change PDF bookmarks)
  * full  — a plain (no-diff) compile of a single commit
"""

from __future__ import annotations

import argparse
import glob
import json
import os
import queue
import re
import shutil
import subprocess
import tempfile
import threading
import time
import urllib.parse
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

HERE = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.dirname(HERE)
INDEX_HTML = os.path.join(HERE, "index.html")
BOOKMARK_FILTER = os.path.join(HERE, "diff_bookmarks.py")

# Filled in from CLI args in main().
CONFIG = {
    "main": "main.tex",
    "build_dir": "build",  # matches $out_dir in latexmkrc
    "out_dir": os.path.join(REPO_ROOT, "build", "diffs"),
}

# A hung build (e.g. latex/git waiting on a prompt) is killed after this and
# marked as an error, so it never blocks the worker forever.
BUILD_TIMEOUT = 420  # seconds

# ---------------------------------------------------------------------------
# Job state
# ---------------------------------------------------------------------------

JOBS_LOCK = threading.Lock()
INDEX_IO_LOCK = threading.Lock()    # serialise index.json writes across threads
JOBS: dict[str, dict] = {}          # id -> job dict
BUILD_QUEUE: "queue.Queue[str]" = queue.Queue()


def index_path() -> str:
    return os.path.join(CONFIG["out_dir"], "index.json")


def now_iso() -> str:
    # astimezone() with no arg uses the container's local zone (TZ env).
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def safe(token: str) -> str:
    return re.sub(r"[^0-9a-zA-Z]", "_", token)


def diff_id(old: str, new: str) -> str:
    return f"{old}..{new}"


def full_id(commit: str) -> str:
    return f"full:{commit}"


def pdf_name(job: dict) -> str:
    if job["kind"] == "full":
        return f"full_{safe(job['commit'])}.pdf"
    return f"diff_{safe(job['old'])}__{safe(job['new'])}.pdf"


def public_job(job: dict) -> dict:
    """A copy safe to send to the browser (no big log blobs)."""
    out = {k: v for k, v in job.items() if k != "log"}
    out["has_pdf"] = bool(job.get("pdf") and os.path.exists(
        os.path.join(CONFIG["out_dir"], job["pdf"])))
    out["log_tail"] = "\n".join((job.get("log") or "").splitlines()[-40:])
    return out


def save_index() -> None:
    os.makedirs(CONFIG["out_dir"], exist_ok=True)
    with JOBS_LOCK:
        data = {jid: {k: v for k, v in j.items() if k != "log"}
                for jid, j in JOBS.items()}
    with INDEX_IO_LOCK:   # unique tmp + serialised replace: no cross-thread race
        fd, tmp = tempfile.mkstemp(dir=CONFIG["out_dir"], suffix=".tmp")
        with os.fdopen(fd, "w") as fh:
            json.dump(data, fh, indent=2)
        os.replace(tmp, index_path())


def load_index() -> None:
    try:
        with open(index_path()) as fh:
            data = json.load(fh)
    except (OSError, ValueError):
        return
    with JOBS_LOCK:
        for jid, job in data.items():
            job.setdefault("kind", "diff")
            # Anything left "building" from a previous run was interrupted.
            if job.get("status") in ("building", "queued"):
                job["status"] = "error"
                job["error"] = "Interrupted (server restarted during build)."
            if job.get("status") == "done":
                pdf = job.get("pdf")
                if not pdf or not os.path.exists(os.path.join(CONFIG["out_dir"], pdf)):
                    job["status"] = "error"
                    job["error"] = "PDF missing."
            JOBS[jid] = job


# ---------------------------------------------------------------------------
# Git helpers
# ---------------------------------------------------------------------------

def git(*args: str, timeout: int = 120) -> str:
    env = dict(os.environ)
    env["GIT_TERMINAL_PROMPT"] = "0"   # never block on a credential prompt
    return subprocess.check_output(
        ["git", *args], cwd=REPO_ROOT, text=True, stderr=subprocess.STDOUT,
        env=env, timeout=timeout)


CHGMETA_RE = re.compile(r"\\difchgmeta\{(\d+)\}\{(add|del)\}\{(\d+)\}\{([^}]*)\}")


def parse_changes(aux_path: str) -> list[dict]:
    """Read the \\difchgmeta records the diff filter wrote into the .aux and
    collapse them to one entry per changed page (a change in a heading fires
    several times — body, TOC, running head — so per-record entries are noisy).
    Each entry has the physical page (for jumping), printed page (label), and a
    type of add / del / both, renumbered 1..N in page order."""
    try:
        with open(aux_path, encoding="utf-8", errors="replace") as fh:
            text = fh.read()
    except OSError:
        return []
    pages: dict[int, dict] = {}
    for m in CHGMETA_RE.finditer(text):
        typ, abspage, page = m.group(2), int(m.group(3)), m.group(4)
        e = pages.setdefault(abspage, {"abspage": abspage, "page": page,
                                       "types": set()})
        e["types"].add(typ)
    out = []
    for i, e in enumerate(sorted(pages.values(), key=lambda x: x["abspage"]), 1):
        types = e["types"]
        typ = "both" if len(types) > 1 else next(iter(types))
        out.append({"n": i, "type": typ,
                    "abspage": e["abspage"], "page": e["page"]})
    return out


def list_commits(limit: int = 200) -> list[dict]:
    # hash <US> short <US> author <US> local date+time <US> subject
    fmt = "%H%x1f%h%x1f%an%x1f%ad%x1f%s"
    out = git("log", f"-{limit}", "--date=format-local:%Y-%m-%d %H:%M",
              f"--pretty=format:{fmt}")
    commits = []
    for line in out.splitlines():
        if not line.strip():
            continue
        full, short, author, date, subject = line.split("\x1f")
        commits.append({
            "hash": full, "short": short, "author": author,
            "date": date, "subject": subject,
        })
    return commits


def commit_map() -> dict[str, dict]:
    """Map both full and short hashes -> {short, subject, date}."""
    m: dict[str, dict] = {}
    try:
        for c in list_commits(500):
            info = {"short": c["short"], "subject": c["subject"], "date": c["date"]}
            m[c["short"]] = info
            m[c["hash"]] = info
    except Exception:  # noqa: BLE001
        pass
    return m


def copy_untracked_assets(dest_root: str) -> None:
    """Mirror gitignored-but-present figure assets (e.g. *.pdf) into a checkout,
    the same way git-latexdiff's --ln-untracked does for the diff build."""
    fig_root = os.path.join(REPO_ROOT, "figures")
    for dirpath, _dirs, files in os.walk(fig_root):
        for name in files:
            if not name.lower().endswith(".pdf"):
                continue
            src = os.path.join(dirpath, name)
            rel = os.path.relpath(src, REPO_ROOT)
            dst = os.path.join(dest_root, rel)
            if not os.path.exists(dst):
                os.makedirs(os.path.dirname(dst), exist_ok=True)
                shutil.copy2(src, dst)


# ---------------------------------------------------------------------------
# Build worker
# ---------------------------------------------------------------------------

def build_worker() -> None:
    while True:
        jid = BUILD_QUEUE.get()
        try:
            with JOBS_LOCK:
                kind = JOBS[jid]["kind"]
            if kind == "full":
                run_full_build(jid)
            else:
                run_diff_build(jid)
        except Exception as exc:  # noqa: BLE001 - never let the worker die
            with JOBS_LOCK:
                job = JOBS.get(jid)
                if job:
                    job["status"] = "error"
                    job["error"] = f"{type(exc).__name__}: {exc}"
            save_index()
        finally:
            BUILD_QUEUE.task_done()


def _run_streamed(cmd: list[str], cwd: str, jid: str,
                  timeout: int = BUILD_TIMEOUT) -> tuple[int, list[str]]:
    """Run cmd, stream its output into the job log, kill it if it hangs."""
    env = dict(os.environ)
    env["GIT_TERMINAL_PROMPT"] = "0"
    proc = subprocess.Popen(cmd, cwd=cwd, text=True, env=env,
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    timed_out = {"v": False}

    def _kill():
        timed_out["v"] = True
        try:
            proc.kill()
        except Exception:  # noqa: BLE001
            pass

    watchdog = threading.Timer(timeout, _kill)
    watchdog.start()
    log_lines: list[str] = []
    try:
        assert proc.stdout is not None
        for line in proc.stdout:
            log_lines.append(line.rstrip("\n"))
            with JOBS_LOCK:
                JOBS[jid]["log"] = "\n".join(log_lines[-400:])
        rc = proc.wait()
    finally:
        watchdog.cancel()
    if timed_out["v"]:
        log_lines.append(f"[diff-viewer] build exceeded {timeout}s and was killed.")
        rc = -99
    return rc, log_lines


def _start(jid: str) -> dict:
    with JOBS_LOCK:
        job = JOBS[jid]
        job["status"] = "building"
        job["error"] = None
        job["started"] = now_iso()
        job["log"] = ""
    save_index()
    return job


def _finish(jid: str, out_pdf: str, rc: int, log_lines: list[str],
            elapsed: float, what: str) -> None:
    with JOBS_LOCK:
        job = JOBS[jid]
        job["log"] = "\n".join(log_lines[-400:])
        job["elapsed"] = elapsed
        job["finished"] = now_iso()
        if os.path.exists(out_pdf):
            job["status"] = "done"
            job["pdf"] = os.path.basename(out_pdf)
            job["error"] = None
        else:
            job["status"] = "error"
            job["error"] = (f"{what} exited {rc} and produced no PDF. "
                            "See the build log below.")
    save_index()


def run_diff_build(jid: str) -> None:
    job = _start(jid)
    old, new = job["old"], job["new"]
    out_pdf = os.path.join(CONFIG["out_dir"], pdf_name(job))
    if os.path.exists(out_pdf):
        os.remove(out_pdf)

    # --ln-untracked symlinks the (untracked) build/ dir from the working tree
    # back into the checkout, so latexmk writes its .aux into the *real* build/.
    # That file survives git-latexdiff's cleanup, so we read the change records
    # the filter wrote there after the build (and use -o for a reliable PDF).
    aux_path = os.path.join(REPO_ROOT, CONFIG["build_dir"], "main.aux")
    for p in (out_pdf, aux_path):
        if os.path.exists(p):
            os.remove(p)

    cmd = [
        "git", "latexdiff",
        "--main", CONFIG["main"],
        "--latexmk",
        "--build-dir", CONFIG["build_dir"],   # latexmkrc sets $out_dir = 'build'
        "--ln-untracked",                      # pull in gitignored figures (*.pdf)
        "--add-to-config=VERBATIMLINEENV=code",
        "--filter", f"python3 {BOOKMARK_FILTER} {CONFIG['main']}",
        "--ignore-latex-errors",
        "--no-view",
        "--quiet",
        "-o", out_pdf,
        old, new,
    ]
    start = time.time()
    rc, log_lines = _run_streamed(cmd, REPO_ROOT, jid)
    changes = parse_changes(aux_path) if os.path.exists(out_pdf) else []
    with JOBS_LOCK:
        JOBS[jid]["changes"] = changes
    # tidy the compile artifacts the symlink left in build/ (keep build/diffs/).
    for f in glob.glob(os.path.join(REPO_ROOT, CONFIG["build_dir"], "main.*")):
        try:
            os.remove(f)
        except OSError:
            pass
    _finish(jid, out_pdf, rc, log_lines, round(time.time() - start, 1),
            "git-latexdiff")


def run_full_build(jid: str) -> None:
    job = _start(jid)
    commit = job["commit"]
    out_pdf = os.path.join(CONFIG["out_dir"], pdf_name(job))
    if os.path.exists(out_pdf):
        os.remove(out_pdf)

    wt = tempfile.mkdtemp(prefix="thesis-full-")
    start = time.time()
    log_lines: list[str] = []
    rc = -1
    try:
        git("worktree", "add", "--detach", "--force", wt, commit)
        copy_untracked_assets(wt)
        # Same engine as build.sh: latexmk + the repo's latexmkrc (out_dir=build).
        rc, log_lines = _run_streamed(
            ["latexmk", "-pdf", "-f", "-interaction=nonstopmode", CONFIG["main"]],
            wt, jid)
        built = os.path.join(wt, CONFIG["build_dir"], "main.pdf")
        if os.path.exists(built):
            shutil.copy2(built, out_pdf)
    finally:
        subprocess.run(["git", "worktree", "remove", "--force", wt],
                       cwd=REPO_ROOT, capture_output=True, text=True)
        shutil.rmtree(wt, ignore_errors=True)
    _finish(jid, out_pdf, rc, log_lines, round(time.time() - start, 1), "latexmk")


def enqueue(job: dict) -> dict:
    jid = job["id"]
    with JOBS_LOCK:
        existing = JOBS.get(jid)
        if existing and existing.get("status") in ("building", "queued"):
            return public_job(existing)
        JOBS[jid] = job
        result = public_job(job)
    save_index()
    BUILD_QUEUE.put(jid)
    return result


def enqueue_diff(old: str, new: str) -> dict:
    cm = commit_map()
    o, n = cm.get(old, {}), cm.get(new, {})
    return enqueue({
        "id": diff_id(old, new), "kind": "diff",
        "old": old, "new": new,
        "old_subject": o.get("subject", ""), "new_subject": n.get("subject", ""),
        "old_date": o.get("date", ""), "new_date": n.get("date", ""),
        "status": "queued", "created": now_iso(),
        "pdf": None, "error": None, "log": "",
    })


def enqueue_full(commit: str) -> dict:
    info = commit_map().get(commit, {})
    return enqueue({
        "id": full_id(commit), "kind": "full",
        "commit": commit,
        "subject": info.get("subject", ""), "date": info.get("date", ""),
        "status": "queued", "created": now_iso(),
        "pdf": None, "error": None, "log": "",
    })


def ensure_current_full() -> None:
    """Pin a 'current draft' = the full PDF of HEAD, auto-built on startup so it
    is ready to view.  Drops the previous auto-current (an older HEAD) to avoid
    piling up stale drafts; manually-built full PDFs and diffs are left alone."""
    try:
        head = git("rev-parse", "HEAD").strip()
    except Exception:  # noqa: BLE001
        return
    cur_id = full_id(head)

    # Remove stale auto-current drafts (older HEADs).
    stale = []
    with JOBS_LOCK:
        for jid, j in list(JOBS.items()):
            if j.get("auto") and jid != cur_id:
                stale.append((jid, j.get("pdf")))
                JOBS.pop(jid, None)
        for j in JOBS.values():
            j.pop("current", None)
        existing = JOBS.get(cur_id)
    for _, pdf in stale:
        if pdf:
            try:
                os.remove(os.path.join(CONFIG["out_dir"], pdf))
            except OSError:
                pass

    have = bool(existing and existing.get("status") == "done"
                and existing.get("pdf")
                and os.path.exists(os.path.join(CONFIG["out_dir"], existing["pdf"])))
    if not have:
        enqueue_full(head)
    with JOBS_LOCK:
        JOBS[cur_id]["current"] = True
        JOBS[cur_id]["auto"] = True
    save_index()


# ---------------------------------------------------------------------------
# HTTP handler
# ---------------------------------------------------------------------------

class Handler(BaseHTTPRequestHandler):
    server_version = "latexdiff-ui/1.1"

    def log_message(self, fmt, *args):  # quieter logs
        pass

    # -- helpers ----------------------------------------------------------
    def _send_json(self, obj, code=200):
        body = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_bytes(self, body: bytes, ctype: str, code=200, extra=None):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(body)

    def _read_json(self) -> dict:
        length = int(self.headers.get("Content-Length", 0))
        if not length:
            return {}
        raw = self.rfile.read(length)
        try:
            return json.loads(raw)
        except ValueError:
            return {}

    # -- routes -----------------------------------------------------------
    def do_GET(self):
        path = urllib.parse.urlparse(self.path).path
        if path in ("/", "/index.html"):
            self._serve_index()
        elif path == "/api/commits":
            self._api_commits()
        elif path == "/api/diffs":
            self._api_diffs()
        elif path.startswith("/api/diff/"):
            self._api_diff_status(urllib.parse.unquote(path[len("/api/diff/"):]))
        elif path.startswith("/pdf/"):
            self._serve_pdf(urllib.parse.unquote(path[len("/pdf/"):]))
        else:
            self._send_json({"error": "not found"}, 404)

    def do_POST(self):
        path = urllib.parse.urlparse(self.path).path
        if path == "/api/diff":
            self._api_create_diff()
        elif path == "/api/full":
            self._api_create_full()
        else:
            self._send_json({"error": "not found"}, 404)

    def do_DELETE(self):
        path = urllib.parse.urlparse(self.path).path
        if path.startswith("/api/diff/"):
            self._api_delete(urllib.parse.unquote(path[len("/api/diff/"):]))
        else:
            self._send_json({"error": "not found"}, 404)

    # -- handlers ---------------------------------------------------------
    def _serve_index(self):
        try:
            with open(INDEX_HTML, "rb") as fh:
                body = fh.read()
        except OSError:
            self._send_bytes(b"index.html missing", "text/plain", 500)
            return
        self._send_bytes(body, "text/html; charset=utf-8")

    def _api_commits(self):
        try:
            self._send_json({"commits": list_commits()})
        except subprocess.CalledProcessError as exc:
            self._send_json({"error": exc.output}, 500)

    def _api_diffs(self):
        with JOBS_LOCK:
            jobs = [public_job(j) for j in JOBS.values()]
        jobs.sort(key=lambda j: j.get("created", ""), reverse=True)
        self._send_json({"diffs": jobs})

    def _api_diff_status(self, jid):
        with JOBS_LOCK:
            job = JOBS.get(jid)
            payload = public_job(job) if job else None
        if payload is None:
            self._send_json({"error": "unknown job"}, 404)
        else:
            self._send_json(payload)

    def _api_create_diff(self):
        data = self._read_json()
        old = (data.get("old") or "").strip()
        new = (data.get("new") or "").strip()
        if not old or not new:
            self._send_json({"error": "old and new commits are required"}, 400)
            return
        if old == new:
            self._send_json({"error": "pick two different commits"}, 400)
            return
        self._send_json(enqueue_diff(old, new))

    def _api_create_full(self):
        data = self._read_json()
        commit = (data.get("commit") or "").strip()
        if not commit:
            self._send_json({"error": "commit is required"}, 400)
            return
        self._send_json(enqueue_full(commit))

    def _api_delete(self, jid):
        with JOBS_LOCK:
            job = JOBS.pop(jid, None)
        if job and job.get("pdf"):
            try:
                os.remove(os.path.join(CONFIG["out_dir"], job["pdf"]))
            except OSError:
                pass
        save_index()
        self._send_json({"ok": True})

    def _serve_pdf(self, jid):
        with JOBS_LOCK:
            job = JOBS.get(jid)
            pdf = job.get("pdf") if job else None
        if not pdf:
            self._send_bytes(b"no pdf", "text/plain", 404)
            return
        full = os.path.join(CONFIG["out_dir"], pdf)
        if not os.path.exists(full):
            self._send_bytes(b"pdf missing", "text/plain", 404)
            return
        with open(full, "rb") as fh:
            body = fh.read()
        self._send_bytes(body, "application/pdf", extra={
            "Content-Disposition": f'inline; filename="{pdf}"',
            # Cache so jumping to a change (#page=N) reloads from cache, not net.
            "Cache-Control": "private, max-age=600"})


def main():
    ap = argparse.ArgumentParser(description="git-latexdiff web UI")
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--main", default="main.tex",
                    help="main LaTeX file (relative to repo root)")
    args = ap.parse_args()
    CONFIG["main"] = args.main

    os.makedirs(CONFIG["out_dir"], exist_ok=True)
    load_index()

    worker = threading.Thread(target=build_worker, daemon=True)
    worker.start()
    ensure_current_full()   # auto-build the latest full PDF as the "current draft"

    httpd = ThreadingHTTPServer((args.host, args.port), Handler)
    url = f"http://{args.host}:{args.port}"
    print(f"git-latexdiff UI  ->  {url}", flush=True)
    print(f"repo: {REPO_ROOT}", flush=True)
    print(f"main: {CONFIG['main']}   out: {CONFIG['out_dir']}", flush=True)
    print("Ctrl-C to stop.", flush=True)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nbye")


if __name__ == "__main__":
    main()
