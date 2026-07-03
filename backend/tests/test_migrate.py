import json

from ocd_core.db import migrate
from ocd_core.db.engine import session
from ocd_core.db.models import Conversation, Project
from sqlmodel import select


def _seed_tree(root):
    (root / "_registry.json").write_text(json.dumps([
        {"id": "alpha", "name": "Alpha", "created_at": "2026-01-01T00:00:00+00:00"},
    ]), encoding="utf-8")
    pdir = root / "alpha"
    (pdir / "knowledge").mkdir(parents=True)
    (pdir / "instructions.md").write_text("do alpha", encoding="utf-8")
    (pdir / "allowlist.json").write_text(json.dumps(["aj360.events"]), encoding="utf-8")
    cdir = pdir / "conversations"
    cdir.mkdir()
    (cdir / "c1.json").write_text(json.dumps({
        "id": "c1", "title": "Chat 1", "created_at": "2026-01-02T00:00:00+00:00",
        "updated_at": "2026-01-03T00:00:00+00:00", "pinned": True,
        "messages": [{"role": "user", "content": "hi", "kind": "user"}]}), encoding="utf-8")
    gdir = root / "general" / "conversations"
    gdir.mkdir(parents=True)
    (gdir / "g1.json").write_text(json.dumps({
        "id": "g1", "title": "General", "created_at": "2026-01-04T00:00:00+00:00",
        "updated_at": "2026-01-04T00:00:00+00:00", "messages": []}), encoding="utf-8")


def test_migrate_counts_and_fidelity(db, tmp_path):
    _seed_tree(tmp_path)
    result = migrate.migrate_filesystem_to_db(tmp_path)
    assert result == {"projects": 1, "conversations": 2}
    with session() as s:
        p = s.get(Project, "alpha")
        assert p.name == "Alpha" and p.instructions == "do alpha" and p.allowlist == ["aj360.events"]
        c = s.get(Conversation, "c1")
        assert c.project_id == "alpha" and c.pinned is True and c.transcript[0]["content"] == "hi"
        assert s.get(Conversation, "g1").project_id == "general"


def test_migrate_is_idempotent(db, tmp_path):
    _seed_tree(tmp_path)
    migrate.migrate_filesystem_to_db(tmp_path)
    again = migrate.migrate_filesystem_to_db(tmp_path)
    assert again == {"projects": 1, "conversations": 2}
    with session() as s:
        assert len(s.exec(select(Conversation)).all()) == 2  # no duplicates


def test_legacy_chat_history_fold_is_idempotent(db, tmp_path):
    import json
    pdir = tmp_path / "oldproj" / "conversations"
    pdir.mkdir(parents=True)
    (tmp_path / "oldproj" / "chat_history.json").write_text(json.dumps(
        [{"role": "user", "content": "legacy hi", "kind": "user"}]), encoding="utf-8")
    from ocd_core.db.engine import session
    from ocd_core.db.models import Conversation
    from sqlmodel import select
    migrate.migrate_filesystem_to_db(tmp_path)
    migrate.migrate_filesystem_to_db(tmp_path)  # re-run
    with session() as s:
        rows = s.exec(select(Conversation).where(Conversation.project_id == "oldproj")).all()
        assert len(rows) == 1  # folded once, not duplicated
        assert rows[0].id == "legacy-oldproj" and rows[0].transcript[0]["content"] == "legacy hi"
