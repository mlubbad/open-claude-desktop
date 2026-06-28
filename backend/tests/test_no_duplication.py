import pathlib

CORE = pathlib.Path("frontend/aj360_app/core.py")


def test_core_has_no_domain_defs():
    text = CORE.read_text(encoding="utf-8")
    for banned in ("def execute_sql", "def create_project", "def get_settings",
                   "def search_schema", "def run_turn", "def ingest_file_to_kb",
                   "def _build_catalog_sync"):
        assert banned not in text, f"{banned} still defined in core.py shim"


def test_single_definition_homes():
    import ocd_core.bigquery, ocd_core.projects, ocd_core.agent, ocd_core.settings, ocd_core.schema_catalog
    assert ocd_core.bigquery.execute_sql.__module__ == "ocd_core.bigquery"
    assert ocd_core.projects.create_project.__module__ == "ocd_core.projects"
    assert ocd_core.agent.run_turn.__module__ == "ocd_core.agent"
    assert ocd_core.settings.get_settings.__module__ == "ocd_core.settings"
    assert ocd_core.schema_catalog.search_schema.__module__ == "ocd_core.schema_catalog"


def test_reflex_shims_are_thin():
    # agent.py and integrations.py shims re-export only
    for name in ("agent.py", "integrations.py"):
        p = pathlib.Path("frontend/aj360_app") / name
        text = p.read_text(encoding="utf-8")
        assert "import ocd_core" in text or "from ocd_core" in text
        assert "def " not in text, f"{name} shim still defines functions"
