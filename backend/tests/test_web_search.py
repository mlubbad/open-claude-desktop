"""Pluggable web-search provider: pure DDG-HTML + SearXNG-JSON parsers, result
normalization, and provider dispatch/fallback — all without network access."""
from ocd_core import config, integrations


def test_parse_ddg_html_extracts_results_and_unwraps_urls():
    html = """
    <a class="result__a" href="//duckduckgo.com/l/?uddg=https%3A%2F%2Fexample.com%2Fa">
      First <b>title</b></a>
    <a class="result__snippet" href="x">A short <b>snippet</b> here.</a>
    <a class="result__a" href="https://www.python.org/">Python</a>
    <a class="result__snippet" href="y">The Python site.</a>
    """
    out = integrations._parse_ddg_html(html, 5)
    assert len(out) == 2
    assert out[0]["url"] == "https://example.com/a"  # /l/?uddg= unwrapped
    assert out[0]["title"] == "First title"  # tags stripped
    assert out[0]["snippet"] == "A short snippet here."
    assert out[0]["domain"] == "example.com"
    assert out[0]["favicon"].startswith("https://www.google.com/s2/favicons?domain=example.com")
    assert out[1]["domain"] == "python.org"  # www. stripped


def test_parse_ddg_html_respects_n():
    html = "".join(
        f'<a class="result__a" href="https://s{i}.com/">T{i}</a>'
        f'<a class="result__snippet" href="x">Snip {i}</a>'
        for i in range(10)
    )
    assert len(integrations._parse_ddg_html(html, 3)) == 3


def test_parse_searxng_json_maps_fields():
    data = {"results": [
        {"title": "Alpha", "url": "https://alpha.test/x", "content": "about alpha"},
        {"title": "Beta", "url": "https://www.beta.test/", "content": "about beta"},
        {"title": "", "url": "https://notitle.test/"},  # dropped (no title)
    ]}
    out = integrations._parse_searxng_json(data, 5)
    assert [r["title"] for r in out] == ["Alpha", "Beta"]
    assert out[0]["snippet"] == "about alpha"  # SearXNG 'content' -> snippet
    assert out[1]["domain"] == "beta.test"


def test_parse_searxng_json_handles_garbage():
    assert integrations._parse_searxng_json({}, 5) == []
    assert integrations._parse_searxng_json({"results": "nope"}, 5) == []
    assert integrations._parse_searxng_json(None, 5) == []  # type: ignore[arg-type]


def test_result_item_drops_incomplete():
    assert integrations._result_item("", "https://x.com", "s") is None
    assert integrations._result_item("t", "", "s") is None
    assert integrations._result_item("t", "https://x.com", "")["snippet"] == ""


def test_web_results_empty_query_short_circuits():
    assert integrations._web_results("") == []
    assert integrations._web_results("   ") == []


def test_web_results_uses_searxng_when_configured(db, monkeypatch):
    from ocd_core import settings
    settings.save_settings({"search_provider": "searxng", "searxng_url": "http://localhost:8888"})
    calls = {}

    def fake_searxng(query, n, base_url):
        calls["searxng"] = (query, n, base_url)
        return [{"title": "S", "url": "https://s.test/", "snippet": "hit", "domain": "s.test", "favicon": ""}]

    def fake_ddg(query, n):
        calls["ddg"] = True
        return []

    monkeypatch.setattr(integrations, "_searxng_results", fake_searxng)
    monkeypatch.setattr(integrations, "_ddg_html_results", fake_ddg)
    out = integrations._web_results("hello", 4)
    assert out and out[0]["title"] == "S"
    assert calls["searxng"] == ("hello", 4, "http://localhost:8888")
    assert "ddg" not in calls  # SearXNG succeeded -> no fallback


def test_web_results_falls_back_to_ddg_when_searxng_empty(db, monkeypatch):
    from ocd_core import settings
    settings.save_settings({"search_provider": "searxng", "searxng_url": "http://localhost:8888"})
    monkeypatch.setattr(integrations, "_searxng_results", lambda q, n, u: [])  # SearXNG down
    monkeypatch.setattr(integrations, "_ddg_html_results",
                        lambda q, n: [{"title": "D", "url": "https://d.test/", "snippet": "",
                                       "domain": "d.test", "favicon": ""}])
    out = integrations._web_results("hello", 4)
    assert out and out[0]["title"] == "D"  # degraded to the keyless fallback


def test_web_results_defaults_to_ddg(db, monkeypatch):
    # Default settings have no searxng_url -> DDG path only.
    monkeypatch.setattr(integrations, "_ddg_html_results",
                        lambda q, n: [{"title": "DDG", "url": "https://x.test/", "snippet": "",
                                       "domain": "x.test", "favicon": ""}])
    called = {"searxng": False}
    monkeypatch.setattr(integrations, "_searxng_results",
                        lambda q, n, u: called.__setitem__("searxng", True) or [])
    out = integrations._web_results("hi", 3)
    assert out[0]["title"] == "DDG"
    assert called["searxng"] is False


def test_searxng_rejects_non_http_url():
    assert integrations._searxng_results("q", 5, "ftp://evil") == []
    assert integrations._searxng_results("q", 5, "") == []


def test_search_provider_is_a_known_setting():
    assert "search_provider" in config.DEFAULT_SETTINGS
    assert "searxng_url" in config.DEFAULT_SETTINGS
