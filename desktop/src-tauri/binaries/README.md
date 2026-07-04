# Backend sidecar binaries

Tauri bundles the backend as an **externalBin** sidecar named
`ocd-backend-<target-triple>` (e.g. `ocd-backend-x86_64-unknown-linux-gnu`).

These files are **build artifacts** and are gitignored. The release CI freezes
the FastAPI backend with PyInstaller (`desktop/scripts/build-backend-sidecar.sh`),
names the output with the runner's Rust target triple, and drops it here before
`tauri build`. For a local `cargo check`/`cargo build`, a small placeholder stub
is enough — `lib.rs` spawns whatever binary is bundled.
