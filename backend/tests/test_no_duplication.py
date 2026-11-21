import pathlib


def test_legacy_reflex_frontend_is_retired():
    assert not pathlib.Path("frontend").exists(), "legacy Reflex frontend should remain removed"


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
