#!/usr/bin/env bash
# Download the official Node.js runtime binary and place it where Tauri's externalBin
# expects it: desktop/src-tauri/binaries/ocd-node-<target-triple>[.exe]. Bundling Node
# lets .mcpb extensions that launch `node` run on machines with no system install —
# the shell hands the backend its path as OCD_NODE (see lib.rs / integrations.py).
# Named ocd-node, not node: the Linux .deb installs external binaries into /usr/bin,
# where a bare `node` would collide with the distro's nodejs package.
#
# Run before `tauri build` (release.yml does) and once for local dev builds. The
# version is pinned; bump it deliberately (override with NODE_VERSION=…).
set -euo pipefail

NODE_VERSION="${NODE_VERSION:-22.17.0}"

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
OUT_DIR="$REPO/desktop/src-tauri/binaries"

# Tauri names sidecars with the Rust target triple (host by default; arg overrides).
TRIPLE="${1:-$(rustc -Vv 2>/dev/null | sed -n 's/^host: //p')}"
if [ -z "${TRIPLE:-}" ]; then
  echo "error: pass a target triple or install rustc" >&2
  exit 1
fi

case "$TRIPLE" in
  x86_64-pc-windows-*)       DIST="win-x64"      EXT="zip"    BIN="node.exe" ;;
  aarch64-pc-windows-*)      DIST="win-arm64"    EXT="zip"    BIN="node.exe" ;;
  x86_64-apple-darwin)       DIST="darwin-x64"   EXT="tar.gz" BIN="bin/node" ;;
  aarch64-apple-darwin)      DIST="darwin-arm64" EXT="tar.gz" BIN="bin/node" ;;
  x86_64-unknown-linux-gnu)  DIST="linux-x64"    EXT="tar.xz" BIN="bin/node" ;;
  aarch64-unknown-linux-gnu) DIST="linux-arm64"  EXT="tar.xz" BIN="bin/node" ;;
  *) echo "error: no Node dist mapping for triple '$TRIPLE'" >&2; exit 1 ;;
esac

EXE_SUFFIX=""
case "$TRIPLE" in *windows*) EXE_SUFFIX=".exe" ;; esac
TARGET="$OUT_DIR/ocd-node-$TRIPLE$EXE_SUFFIX"
if [ -f "$TARGET" ]; then
  echo "Node sidecar already present: $TARGET"
  exit 0
fi

NAME="node-v$NODE_VERSION-$DIST"
URL="https://nodejs.org/dist/v$NODE_VERSION/$NAME.$EXT"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

echo "Fetching $URL"
curl -fsSL "$URL" -o "$TMP/node.$EXT"

if [ "$EXT" = "zip" ]; then
  # Windows runners: pull the one binary out with Python's zipfile (the tar on the
  # git-bash PATH is GNU tar, which can't read zips).
  python - "$TMP/node.zip" "$NAME/$BIN" "$TMP/node.exe" <<'PY'
import pathlib
import sys
import zipfile

src, member, dest = sys.argv[1:4]
with zipfile.ZipFile(src) as zf:
    pathlib.Path(dest).write_bytes(zf.read(member))
PY
else
  tar -xf "$TMP/node.$EXT" -C "$TMP" "$NAME/$BIN"
  mv "$TMP/$NAME/$BIN" "$TMP/node"
fi

mkdir -p "$OUT_DIR"
cp "$TMP/node$EXE_SUFFIX" "$TARGET"
chmod +x "$TARGET" 2>/dev/null || true
echo "Node sidecar ready: $TARGET"
