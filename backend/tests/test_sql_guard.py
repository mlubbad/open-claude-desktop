"""TDD for the shared ocd_core.sql_guard module (#3 extraction).

This is the single source of truth for the read-only SQL guard that was
previously duplicated (and divergent) across app.py and aj360_app core.py.
"""
from collections import namedtuple

from ocd_core import sql_guard as g

Tbl = namedtuple("Tbl", "project dataset_id table_id")


def test_banned_aliases_set_contents():
    assert "rows" in g.BANNED_ALIASES
    assert "range" in g.BANNED_ALIASES


def test_is_mutation_read_only_by_default():
    assert g.is_mutation("SELECT") is False
    assert g.is_mutation("select") is False
    for stmt in ("INSERT", "UPDATE", "DELETE", "MERGE", "CREATE_TABLE_AS_SELECT"):
        assert g.is_mutation(stmt) is True, stmt
    # Fail-safe: unknown / None counts as a mutation.
    assert g.is_mutation(None) is True
    assert g.is_mutation("") is True
    assert g.is_mutation("UNKNOWN") is True


def test_check_banned_aliases():
    assert g.check_banned_aliases("SELECT 1 AS foo") is None
    err = g.check_banned_aliases("SELECT 1 AS rows")
    assert err and "rows" in err
    # Reserved word used as a parenthesis alias is also caught.
    err2 = g.check_banned_aliases("SELECT * FROM (SELECT 1) range")
    assert err2 and "range" in err2


def test_tables_out_of_scope():
    allowed = {"proj.ds_ok"}
    assert g.tables_out_of_scope([Tbl("proj", "ds_ok", "t")], allowed) == []
    oos = g.tables_out_of_scope(
        [Tbl("proj", "ds_bad", "secrets"), Tbl("proj", "ds_ok", "t")], allowed)
    assert any("ds_bad" in x for x in oos)
    assert all("ds_bad" in x for x in oos)  # only the bad one is flagged
    assert g.tables_out_of_scope([], allowed) == []
    assert g.tables_out_of_scope(None, allowed) == []
    # Cross-project reference is out of scope.
    assert g.tables_out_of_scope([Tbl("other", "ds_ok", "t")], allowed) != []


if __name__ == "__main__":
    funcs = [v for k, v in sorted(globals().items())
             if k.startswith("test_") and callable(v)]
    failures = []
    for f in funcs:
        try:
            f()
            print("PASS", f.__name__)
        except AssertionError as e:
            print("FAIL", f.__name__, e)
            failures.append(f.__name__)
    print("RESULT:", "ALL PASS" if not failures else f"{len(failures)} FAILED: {failures}")
    raise SystemExit(1 if failures else 0)
