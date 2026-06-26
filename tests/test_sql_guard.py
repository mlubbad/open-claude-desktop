"""Regression tests for the C2 SQL safety guard in app.py.

These cover the pure decision helpers used by run_sql:
  * _is_mutation       — read-only-by-default classification (fail-safe)
  * _tables_out_of_scope — dataset-scope enforcement on the engine's parsed refs

They do NOT hit BigQuery: referenced_tables are simulated with lightweight
objects exposing .project/.dataset_id/.table_id, exactly like google.cloud
.bigquery.table.TableReference.

Run:  venv312\\Scripts\\python.exe -m pytest tests/test_sql_guard.py
or:   venv312\\Scripts\\python.exe tests/test_sql_guard.py
"""
import importlib.util
import os
from collections import namedtuple

_HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _load_app():
    spec = importlib.util.spec_from_file_location(
        "aj360app", os.path.join(_HERE, "app.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


app = _load_app()
Tbl = namedtuple("Tbl", "project dataset_id table_id")


# ── _is_mutation: read-only by default, fail-safe on unknown ──────────────
def test_select_is_not_a_mutation():
    assert app._is_mutation("SELECT") is False
    assert app._is_mutation("select") is False


def test_dml_ddl_are_mutations():
    for stmt in ("INSERT", "UPDATE", "DELETE", "MERGE", "CREATE_TABLE_AS_SELECT",
                 "DROP_TABLE", "TRUNCATE_TABLE", "SCRIPT"):
        assert app._is_mutation(stmt) is True, stmt


def test_unknown_or_none_is_treated_as_mutation():
    assert app._is_mutation(None) is True
    assert app._is_mutation("UNKNOWN") is True
    assert app._is_mutation("") is True


# ── _tables_out_of_scope: enforce dataset allow-list on parsed refs ───────
def _allowed_dataset():
    return sorted(app.CATALOG_DATASETS)[0]


def test_in_scope_table_is_allowed():
    t = Tbl(app.PROJECT_ID, _allowed_dataset(), "some_table")
    assert app._tables_out_of_scope([t], app.ALLOWED_TABLE_SCOPES) == []


def test_forbidden_table_is_flagged_even_alongside_allowed():
    refs = [
        Tbl(app.PROJECT_ID, "definitely_not_allowed", "secrets"),
        Tbl(app.PROJECT_ID, _allowed_dataset(), "ok"),
    ]
    oos = app._tables_out_of_scope(refs, app.ALLOWED_TABLE_SCOPES)
    assert any("definitely_not_allowed" in x for x in oos)
    assert all("definitely_not_allowed" in x for x in oos)  # only the bad one


def test_cross_project_table_is_flagged():
    t = Tbl("some-other-project", _allowed_dataset(), "t")
    assert app._tables_out_of_scope([t], app.ALLOWED_TABLE_SCOPES) != []


def test_empty_and_none_refs_are_empty():
    assert app._tables_out_of_scope([], app.ALLOWED_TABLE_SCOPES) == []
    assert app._tables_out_of_scope(None, app.ALLOWED_TABLE_SCOPES) == []


# ── config posture ───────────────────────────────────────────────────────
def test_writes_are_disabled_by_default():
    # With AJ360_ALLOW_WRITES unset, the agent must be read-only.
    if "AJ360_ALLOW_WRITES" not in os.environ:
        assert app.ALLOW_WRITES is False


if __name__ == "__main__":
    # Allow running without pytest installed.
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
