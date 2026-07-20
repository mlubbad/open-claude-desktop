# backend/ocd_core/harness/checkpoints.py
"""Per-workspace file checkpoints for rewind.

Before a turn's FIRST modification of each file, its bytes (or a tombstone for a
not-yet-existing file) are snapshotted under a checkpoint keyed by turn id. Restore
writes snapshots back (or deletes tombstoned new files). Content is stored as plain
files under the app data dir. Bash-side mutations are NOT tracked (documented limit).
"""
from __future__ import annotations

import shutil
from pathlib import Path

from .. import jsonstore
from .workspace_fs import JailError, resolve_in_workspace

MAX_CHECKPOINTS = 100  # reserved: FIFO pruning deferred to Task 14 layout


def _safe_seg(name: str) -> str:
    """checkpoint_id as a single safe path segment (strip any traversal).

    ``Path(id).name`` alone neutralizes a value containing separators (e.g.
    "../evil" -> "evil") but NOT a bare "." or ".." (Path("..").name == ".." --
    pathlib does not lexically collapse ".." the way ``resolve()`` does), which
    would otherwise let ``self.root / ".."`` address the store root's PARENT
    directory. Reject those explicitly too.
    """
    seg = Path(str(name)).name
    return seg if seg and seg not in (".", "..") else "adhoc"


class CheckpointStore:
    def __init__(self, root: Path):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    def _ckpt_dir(self, checkpoint_id: str) -> Path:
        return self.root / _safe_seg(checkpoint_id)

    def _manifest_path(self, checkpoint_id: str) -> Path:
        return self._ckpt_dir(checkpoint_id) / "manifest.json"

    def _manifest(self, checkpoint_id: str) -> dict:
        man = jsonstore.load_json(self._manifest_path(checkpoint_id), {"files": {}})
        if not isinstance(man.get("files"), dict):   # guard a valid-JSON-but-wrong-shape file
            return {"files": {}}
        return man

    def snapshot_before_edit(self, checkpoint_id: str, workspace_root, rel_path: str) -> None:
        try:
            target = resolve_in_workspace(workspace_root, rel_path)
        except JailError:
            return
        rel = target.relative_to(Path(workspace_root).resolve()).as_posix()  # NOT casefolded
        man = self._manifest(checkpoint_id)
        if rel in man["files"]:
            return  # already snapshotted this turn — keep the earliest state
        d = self._ckpt_dir(checkpoint_id)
        d.mkdir(parents=True, exist_ok=True)
        if target.is_file():
            blob = f"{len(man['files'])}.blob"
            shutil.copyfile(target, d / blob)
            man["files"][rel] = {"blob": blob, "existed": True}
        else:
            man["files"][rel] = {"blob": None, "existed": False}
        jsonstore.save_json(self._manifest_path(checkpoint_id), man)

    def list(self, checkpoint_id: str) -> list[dict]:
        man = self._manifest(checkpoint_id)
        if not man.get("files"):
            return []
        return [{"checkpoint_id": checkpoint_id, "files": sorted(man["files"].keys())}]

    def restore(self, checkpoint_id: str, workspace_root, what: str = "files") -> int:
        if what not in ("files", "both"):
            return 0
        man = self._manifest(checkpoint_id)
        d = self._ckpt_dir(checkpoint_id)
        restored = 0
        for rel, meta in (man.get("files") or {}).items():
            try:
                target = resolve_in_workspace(workspace_root, rel)
            except JailError:
                continue
            try:
                if meta.get("existed") and meta.get("blob"):
                    shutil.copyfile(d / meta["blob"], target)
                elif not meta.get("existed") and target.exists():
                    target.unlink()
                restored += 1
            except OSError:
                continue
        return restored
