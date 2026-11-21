def test_ocd_core_importable_from_installed_package():
    import ocd_core
    from ocd_core import sql_guard
    assert hasattr(sql_guard, "check_banned_aliases")
    # the package now lives under backend/, not repo-root
    assert "backend" in ocd_core.__file__.replace("\\", "/")
