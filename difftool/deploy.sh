#!/usr/bin/env bash
# Build the diff-viewer image from the CURRENT repo state and deploy to Fly.
# Re-run this whenever you want the deployed viewer to pick up new commits
# (the repo history is baked into the image at build time).
set -euo pipefail
cd "$(dirname "$0")/.."   # repo root
fly deploy "$@"
echo
echo "Live at: https://$(grep -m1 '^app' fly.toml | cut -d'\"' -f2).fly.dev"
