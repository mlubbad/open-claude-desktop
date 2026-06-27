from ocd_core import sql_guard


def test_empty_allowlist_allows_everything():
    assert sql_guard.tables_off_allowlist("SELECT * FROM anything", []) is False


def test_allowed_table_present_passes():
    assert sql_guard.tables_off_allowlist(
        "SELECT x FROM aj360.events", ["aj360.events"]) is False


def test_no_allowed_table_is_blocked():
    assert sql_guard.tables_off_allowlist(
        "SELECT x FROM other.table", ["aj360.events"]) is True


def test_known_wart_substring_match_is_case_insensitive():
    # KNOWN-WART: substring (not parsed-reference) match — faithful to app.py.
    assert sql_guard.tables_off_allowlist(
        "SELECT 1 -- mentions AJ360.EVENTS in a comment", ["aj360.events"]) is False
