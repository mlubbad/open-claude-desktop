"""MCP OAuth 2.1 host pieces: keychain token storage round-trips, client metadata for
DCR, provider construction (httpx.Auth), and a real loopback redirect catcher."""
import asyncio

import httpx
import pytest
from mcp.shared.auth import OAuthClientInformationFull, OAuthToken
from ocd_core import mcp_oauth, secrets


@pytest.fixture
def mem_store(monkeypatch):
    """Force the in-memory secret store so tests never touch a real keychain."""
    store = secrets.MemoryStore()
    monkeypatch.setattr(secrets, "get_secret_store", lambda: store)
    return store


def test_token_storage_round_trips(mem_store):
    st = mcp_oauth.KeychainTokenStorage("srv1")

    async def go():
        assert await st.get_tokens() is None  # nothing yet
        tok = OAuthToken(access_token="abc123", token_type="Bearer",
                         refresh_token="r-xyz", scope="openid profile")
        await st.set_tokens(tok)
        got = await st.get_tokens()
        assert got is not None
        assert got.access_token == "abc123"
        assert got.refresh_token == "r-xyz"

    asyncio.run(go())


def test_client_info_round_trips(mem_store):
    st = mcp_oauth.KeychainTokenStorage("srv1")

    async def go():
        assert await st.get_client_info() is None
        info = OAuthClientInformationFull(
            client_id="client-1",
            redirect_uris=["http://127.0.0.1:9000/callback"],  # type: ignore[list-item]
        )
        await st.set_client_info(info)
        got = await st.get_client_info()
        assert got is not None and got.client_id == "client-1"

    asyncio.run(go())


def test_corrupt_storage_reads_as_none(mem_store):
    mem_store.set(mcp_oauth._tokens_key("srv1"), "not-json")
    st = mcp_oauth.KeychainTokenStorage("srv1")
    assert asyncio.run(st.get_tokens()) is None


def test_has_tokens_and_summarize(mem_store):
    assert mcp_oauth.has_tokens("srv1") is False
    assert mcp_oauth.summarize_tokens("srv1") == {"authorized": False}

    st = mcp_oauth.KeychainTokenStorage("srv1")
    asyncio.run(st.set_tokens(OAuthToken(access_token="a", token_type="Bearer",
                                         refresh_token="r", scope="openid")))
    assert mcp_oauth.has_tokens("srv1") is True
    summary = mcp_oauth.summarize_tokens("srv1")
    assert summary["authorized"] is True
    assert summary["has_refresh"] is True
    assert summary["scope"] == "openid"
    # The access token itself is never exposed.
    assert "access_token" not in summary


def test_clear_oauth_forgets_everything(mem_store):
    st = mcp_oauth.KeychainTokenStorage("srv1")
    asyncio.run(st.set_tokens(OAuthToken(access_token="a", token_type="Bearer")))
    asyncio.run(st.set_client_info(OAuthClientInformationFull(
        client_id="c", redirect_uris=["http://127.0.0.1:1/callback"])))  # type: ignore[list-item]
    mcp_oauth.clear_oauth("srv1")
    assert mcp_oauth.has_tokens("srv1") is False
    assert asyncio.run(st.get_client_info()) is None


def test_client_metadata_for_dcr():
    md = mcp_oauth.build_client_metadata("http://127.0.0.1:9000/callback", scopes="openid email")
    assert str(md.redirect_uris[0]) == "http://127.0.0.1:9000/callback"
    assert md.token_endpoint_auth_method == "none"  # public client (PKCE)
    assert "authorization_code" in md.grant_types
    assert "refresh_token" in md.grant_types
    assert md.scope == "openid email"


def test_build_oauth_provider_is_httpx_auth(mem_store):
    async def redirect(_url: str) -> None: ...
    async def callback() -> tuple[str, str | None]:
        return ("code", "state")

    prov = mcp_oauth.build_oauth_provider(
        "srv1", "https://mcp.example.com/mcp", "http://127.0.0.1:9000/callback",
        redirect_handler=redirect, callback_handler=callback)
    assert isinstance(prov, httpx.Auth)


def test_loopback_catcher_captures_code_and_state():
    async def go():
        catcher = mcp_oauth.LoopbackAuthCatcher()
        redirect_uri = await catcher.start()
        assert redirect_uri.startswith("http://127.0.0.1:")
        assert redirect_uri.endswith("/callback")

        async with httpx.AsyncClient() as client:
            resp = await client.get(redirect_uri, params={"code": "the-code", "state": "st-1"})
        assert resp.status_code == 200
        assert "Authorized" in resp.text

        code, state = await catcher.wait(timeout=5)
        assert code == "the-code"
        assert state == "st-1"
        await catcher.close()

    asyncio.run(go())


def test_resolve_cfg_injects_oauth_provider(mem_store):
    import httpx
    from ocd_core import integrations
    cfg = {"id": "srv1", "url": "https://mcp.example.com/mcp", "transport": "http",
           "auth_mode": "oauth"}
    resolved = integrations._resolve_cfg(cfg)
    assert isinstance(resolved.get("auth_provider"), httpx.Auth)


def test_resolve_cfg_no_oauth_provider_for_plain_remote(mem_store):
    from ocd_core import integrations
    cfg = {"id": "srv2", "url": "https://mcp.example.com/mcp", "transport": "http"}
    resolved = integrations._resolve_cfg(cfg)
    assert resolved.get("auth_provider") is None


def test_interactive_provider_opens_the_authorize_url(mem_store):
    import asyncio

    opened = {}

    def opener(url: str) -> None:
        opened["url"] = url

    async def callback() -> tuple[str, str | None]:
        return ("code", "state")

    prov = mcp_oauth.interactive_provider(
        "srv1", "https://mcp.example.com/mcp", "http://127.0.0.1:9000/callback",
        open_url=opener, callback=callback)
    assert isinstance(prov, httpx.Auth)
    # The redirect handler opens the browser at the authorize URL.
    handler = mcp_oauth.make_redirect_handler(opener)
    asyncio.run(handler("https://issuer.example.com/authorize?x=1"))
    assert opened["url"] == "https://issuer.example.com/authorize?x=1"


def test_add_oauth_mcp_server_defers_discovery(mem_store, monkeypatch, tmp_path):
    from ocd_core import integrations
    monkeypatch.setattr(integrations, "MCP_FILE", tmp_path / "mcp_servers.json")
    item = integrations.add_oauth_mcp_server("Remote OAuth", "https://mcp.example.com/mcp")
    assert item["auth_mode"] == "oauth"
    assert item["status"] == "unauthorized"
    assert item["tools"] == []
    # Surfaced by the listing with auth_mode + authorized=False (no tokens yet).
    listed = {s["id"]: s for s in integrations.list_mcp_servers()}
    assert listed[item["id"]]["auth_mode"] == "oauth"
    assert listed[item["id"]]["authorized"] is False


def test_authorize_rejects_non_oauth_server(mem_store, monkeypatch, tmp_path):
    from ocd_core import integrations
    monkeypatch.setattr(integrations, "MCP_FILE", tmp_path / "mcp_servers.json")
    try:
        integrations.authorize_mcp_oauth("does-not-exist")
        raise AssertionError("expected ValueError")
    except ValueError as e:
        assert "OAuth" in str(e)


def test_loopback_catcher_handles_missing_state():
    async def go():
        catcher = mcp_oauth.LoopbackAuthCatcher()
        redirect_uri = await catcher.start()
        async with httpx.AsyncClient() as client:
            await client.get(redirect_uri, params={"code": "only-code"})
        code, state = await catcher.wait(timeout=5)
        assert code == "only-code"
        assert state is None
        await catcher.close()

    asyncio.run(go())
