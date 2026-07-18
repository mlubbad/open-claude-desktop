import pathlib


def test_reflex_shims_are_gone():
    # Phase 4 Task 5: the frontend is a thin HTTP/SSE client and imports zero
    # ocd_core. The old re-export shims (core.py / agent.py / integrations.py)
    # were deleted; assert they stay deleted so the decoupling can't regress.
    for name in ("core.py", "agent.py", "integrations.py"):
        p = pathlib.Path("frontend/aj360_app") / name
        assert not p.exists(), f"{name} shim reintroduced — frontend must not re-import ocd_core"


def test_single_definition_homes():
    import ocd_core.agent
    import ocd_core.bigquery
    import ocd_core.projects
    import ocd_core.schema_catalog
    import ocd_core.settings
    assert ocd_core.bigquery.execute_sql.__module__ == "ocd_core.bigquery"
    assert ocd_core.projects.create_project.__module__ == "ocd_core.projects"
    assert ocd_core.agent.run_turn.__module__ == "ocd_core.agent"
    assert ocd_core.settings.get_settings.__module__ == "ocd_core.settings"
    assert ocd_core.schema_catalog.search_schema.__module__ == "ocd_core.schema_catalog"
