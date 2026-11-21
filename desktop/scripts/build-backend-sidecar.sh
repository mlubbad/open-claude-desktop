#!/usr/bin/env bash
# Freeze the FastAPI backend with PyInstaller and place it where Tauri's externalBin
# expects it: desktop/src-tauri/binaries/ocd-backend-<target-triple>[.exe].
#
# Prereqs: a Python env with the backend installed (`pip install -e ./backend[dev]`)
# and PyInstaller (`pip install pyinstaller`). Run from the repo root or anywhere.
set -euo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
BACKEND="$REPO/backend"
OUT_DIR="$REPO/desktop/src-tauri/binaries"

# Tauri names sidecars with the Rust host target triple.
TRIPLE="$(rustc -Vv 2>/dev/null | sed -n 's/^host: //p')"
if [ -z "${TRIPLE:-}" ]; then
  echo "warning: rustc not found; defaulting the triple" >&2
  TRIPLE="$(uname -m)-unknown-linux-gnu"
fi

EXE_SUFFIX=""
case "$TRIPLE" in *windows*) EXE_SUFFIX=".exe" ;; esac

echo "Freezing backend → dist/ocd-backend (onefile; triple: $TRIPLE)"
( cd "$BACKEND" && pyinstaller ocd-backend.spec --noconfirm --clean )

mkdir -p "$OUT_DIR"
# Onefile build: dist/ocd-backend is a single self-contained executable.
cp "$BACKEND/dist/ocd-backend$EXE_SUFFIX" "$OUT_DIR/ocd-backend-$TRIPLE$EXE_SUFFIX"
chmod +x "$OUT_DIR/ocd-backend-$TRIPLE$EXE_SUFFIX" 2>/dev/null || true

echo "Sidecar ready: $OUT_DIR/ocd-backend-$TRIPLE$EXE_SUFFIX"
echo "externalBin already wired in tauri.conf.json as \"binaries/ocd-backend\"."
