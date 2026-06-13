#!/usr/bin/env bash
# Launch the thesis diff viewer and open it in the browser.
set -euo pipefail
cd "$(dirname "$0")/.."   # repo root
PORT="${1:-8765}"
URL="http://127.0.0.1:${PORT}"
( sleep 1; command -v open >/dev/null && open "$URL" || true ) &
exec python3 difftool/server.py --port "$PORT"
