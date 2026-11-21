from ocd_core import sql_guard


def test_parsed_allowlist_blocks_off_list_table():
    assert sql_guard.tables_off_allowlist(["analytics.events"], ["analytics.events"]) is False
    assert sql_guard.tables_off_allowlist(["analytics.users"], ["analytics.events"]) is True
    # any off-list reference blocks, even alongside an allowed one
    assert sql_guard.tables_off_allowlist(["analytics.events", "analytics.users"], ["analytics.events"]) is True


def test_empty_allowlist_allows_all():
    assert sql_guard.tables_off_allowlist(["anything.here"], []) is False


def test_comment_injection_no_longer_bypasses():
    # `SELECT * FROM analytics.users -- analytics.events` resolves referenced_tables to
    # [analytics.users] (the comment is NOT a reference) -> blocked.
    assert sql_guard.tables_off_allowlist(["analytics.users"], ["analytics.events"]) is True


def test_fail_safe_denies_when_refs_unresolved():
    # allowlist in force but the dry-run couldn't resolve any referenced table
    assert sql_guard.tables_off_allowlist([], ["analytics.events"]) is True
    # ...but with no allowlist, unresolved refs are still allowed (no restriction)
    assert sql_guard.tables_off_allowlist([], []) is False


def test_execute_sql_blocks_off_allowlist(monkeypatch, db):
    from ocd_core import bigquery, projects
    projects.create_project("Scoped")
    from ocd_core.db.engine import session
    from ocd_core.db.models import Project
    with session() as s:
        p = s.get(Project, "scoped")
        p.allowlist = ["analytics.events"]
        s.add(p)
    monkeypatch.setattr(bigquery, "_dry_run",
                        lambda sql: (True, "SELECT", 10, ["analytics.users"], None))
    out = bigquery.execute_sql("SELECT * FROM analytics.users", active_project="scoped")
    assert out["ok"] is False and out["error"] == "allowlist"
