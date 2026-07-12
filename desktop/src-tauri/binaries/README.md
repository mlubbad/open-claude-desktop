# Sidecar binaries

Tauri bundles two **externalBin** sidecars here, each named with the Rust target
triple (e.g. `…-x86_64-unknown-linux-gnu`):

- `ocd-backend-<triple>` — the PyInstaller-frozen FastAPI backend. Release CI
  builds it with `desktop/scripts/build-backend-sidecar.sh`.
- `ocd-node-<triple>` — a pinned Node.js runtime so `.mcpb` extensions that
  launch `node` work on machines without a system install (P1-13). Release CI
  fetches it with `desktop/scripts/fetch-node-sidecar.sh`; the shell passes its
  path to the backend as `OCD_NODE`. (Named `ocd-node`, not `node` — the Linux
  .deb installs external binaries into /usr/bin, where a bare `node` would
  collide with the distro's nodejs package.)

These files are **build artifacts** and are gitignored. For a local
`cargo check`/`cargo build`, run the fetch script once (it downloads the real
Node binary) and drop in any small placeholder stub for `ocd-backend` —
`lib.rs` spawns whatever binary is bundled.
