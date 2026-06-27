import importlib

def test_defaults_match_current_values(monkeypatch):
    for k in ("GCP_PROJECT_ID", "CATALOG_DATASETS", "MAX_BYTES_BILLED_GB",
              "QUERY_TIMEOUT_SEC", "RATE_LIMIT_QUERIES", "RATE_LIMIT_WINDOW_SEC"):
        monkeypatch.delenv(k, raising=False)
    cfg = importlib.reload(importlib.import_module("ocd_core.config"))
    assert cfg.PROJECT_ID == "ajgc-dig-jjc-prod-jawacloud-01"
    assert cfg.CATALOG_DATASETS == [
        "aj360", "aj360_platform", "aj360_search_analytics",
        "al_jazeera_data_models", "aj360_ds", "aj360_monitoring",
        "aj360_marts", "aj360_acquisition_analytics"]
    assert cfg.MAX_BYTES_BILLED == 100 * (1024 ** 3)
    assert cfg.QUERY_TIMEOUT_SEC == 300
    assert cfg.MAX_RETURN_ROWS == 50 and cfg.MAX_STORED_ROWS == 5000
    assert cfg.RATE_LIMIT_QUERIES == 20 and cfg.RATE_LIMIT_WINDOW_SEC == 60

def test_env_override(monkeypatch):
    monkeypatch.setenv("GCP_PROJECT_ID", "my-proj")
    monkeypatch.setenv("CATALOG_DATASETS", "a, b ,c")
    cfg = importlib.reload(importlib.import_module("ocd_core.config"))
    assert cfg.PROJECT_ID == "my-proj"
    assert cfg.CATALOG_DATASETS == ["a", "b", "c"]
