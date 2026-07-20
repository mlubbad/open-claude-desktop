# backend/ocd_core/harness/checkpoints.py
"""Per-workspace file checkpoints for rewind.

Before a turn's FIRST modification of each file, its bytes (or a tombstone for a
not-yet-existing file) are snapshotted under a checkpoint keyed by turn id. Restore
writes snapshots back (or deletes tombstoned new files). Content is stored as plain
files under the app data dir. Bash-side mutations are NOT tracked (documented limit).
"""
from __future__ import annotations

import json
import shutil
from pathlib import Path

from .workspace_fs import JailError, resolve_in_workspace

MAX_CHECKPOINTS = 100


class CheckpointStore:
    def __init__(self, root: Path):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    def _dir(self, checkpoint_id: str) -> Path:
        d = self.root / checkpoint_id
        d.mkdir(parents=True, exist_ok=True)
        return d

    def _manifest_path(self, checkpoint_id: str) -> Path:
        return self._dir(checkpoint_id) / "manifest.json"

    def _manifest(self, checkpoint_id: str) -> dict:
        p = self._manifest_path(checkpoint_id)
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {"files": {}}

    def snapshot_before_edit(self, checkpoint_id: str, workspace_root, rel_path: str) -> None:
        try:
            target = resolve_in_workspace(workspace_root, rel_path)
        except JailError:
            return
        rel = target.relative_to(Path(workspace_root).resolve()).as_posix()
        man = self._manifest(checkpoint_id)
        if rel in man["files"]:
            return  # already snapshotted this turn — keep the earliest state
        d = self._dir(checkpoint_id)
        if target.is_file():
            blob = d / (str(len(man["files"])) + ".blob")
            shutil.copyfile(target, blob)
            man["files"][rel] = {"blob": blob.name, "existed": True}
        else:
            man["files"][rel] = {"blob": None, "existed": False}
        self._manifest_path(checkpoint_id).write_text(json.dumps(man), encoding="utf-8")

    def list(self, checkpoint_id: str) -> list[dict]:
        man = self._manifest(checkpoint_id)
        if not man.get("files"):
            return []
        return [{"checkpoint_id": checkpoint_id, "files": sorted(man["files"].keys())}]

    def restore(self, checkpoint_id: str, workspace_root, what: str = "files") -> int:
        if what not in ("files", "both"):
            return 0
        man = self._manifest(checkpoint_id)
        d = self._dir(checkpoint_id)
        restored = 0
        for rel, meta in man.get("files", {}).items():
            try:
                target = resolve_in_workspace(workspace_root, rel)
            except JailError:
                continue
            if meta.get("existed"):
                shutil.copyfile(d / meta["blob"], target)
            elif target.exists():
                target.unlink()
            restored += 1
        return restored
