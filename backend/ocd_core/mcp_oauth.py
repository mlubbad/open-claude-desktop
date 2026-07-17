"""OAuth 2.1 for remote MCP connectors.

Remote MCP servers increasingly require OAuth 2.1 (PKCE + Dynamic Client Registration).
The MCP Python SDK already implements the full protocol as an ``httpx.Auth`` provider
(``OAuthClientProvider``: discovery, DCR, PKCE, token refresh); this module supplies the
two host-specific pieces it needs:

  * ``KeychainTokenStorage`` — persists the issued tokens AND the dynamic client
    registration in the OS keychain (via ``ocd_core.secrets``), so a connector stays
    authorized across restarts and never writes secrets to mcp_servers.json.
  * ``LoopbackAuthCatcher`` — a one-shot ``127.0.0.1`` HTTP listener that captures the
    ``?code=…&state=…`` redirect at the end of the browser authorize step, providing the
    ``redirect_uri`` and the ``callback_handler`` the SDK expects for a desktop app.

Nothing here reaches the network on its own; the interactive authorize is driven by the
desktop shell opening the authorization URL.
"""
from __future__ import annotations

import asyncio
import contextlib
import json
from collections.abc import Awaitable, Callable
from urllib.parse import parse_qs, urlsplit

from mcp.client.auth import OAuthClientProvider
from mcp.shared.auth import OAuthClientInformationFull, OAuthClientMetadata, OAuthToken

from . import egress

from . import secrets

DEFAULT_SCOPES = "openid profile"


def _tokens_key(sid: str) -> str:
    return f"mcp:{sid}:oauth_tokens"


def _client_key(sid: str) -> str:
    return f"mcp:{sid}:oauth_client"


class KeychainTokenStorage:
    """SDK ``TokenStorage`` backed by the OS keychain / encrypted secret store.

    Stores both the issued ``OAuthToken`` and the dynamically-registered
    ``OAuthClientInformationFull`` as JSON, keyed per MCP server id. Reads tolerate
    absent/corrupt entries (returning ``None``) so a first-time connector just triggers
    a fresh registration + authorize.
    """

    def __init__(self, sid: str) -> None:
        self.sid = sid

    def _store(self):
        return secrets.get_secret_store()

    async def get_tokens(self) -> OAuthToken | None:
        raw = self._store().get(_tokens_key(self.sid))
        if not raw:
            return None
        try:
            return OAuthToken.model_validate_json(raw)
        except Exception:
            return None

    async def set_tokens(self, tokens: OAuthToken) -> None:
        self._store().set(_tokens_key(self.sid), tokens.model_dump_json())

    async def get_client_info(self) -> OAuthClientInformationFull | None:
        raw = self._store().get(_client_key(self.sid))
        if not raw:
            return None
        try:
            return OAuthClientInformationFull.model_validate_json(raw)
        except Exception:
            return None

    async def set_client_info(self, client_info: OAuthClientInformationFull) -> None:
        self._store().set(_client_key(self.sid), client_info.model_dump_json())


def clear_oauth(sid: str) -> None:
    """Forget a connector's stored tokens + client registration (on disconnect)."""
    store = secrets.get_secret_store()
    with contextlib.suppress(Exception):
        store.delete(_tokens_key(sid))
    with contextlib.suppress(Exception):
        store.delete(_client_key(sid))


def has_tokens(sid: str) -> bool:
    """Whether a connector already holds an access token (i.e. is authorized)."""
    return bool(secrets.get_secret_store().get(_tokens_key(sid)))


def build_client_metadata(redirect_uri: str, scopes: str = DEFAULT_SCOPES,
                          client_name: str = "Open Claude Desktop") -> OAuthClientMetadata:
    """Client metadata used for Dynamic Client Registration (RFC 7591)."""
    return OAuthClientMetadata(
        client_name=client_name,
        redirect_uris=[redirect_uri],  # type: ignore[list-item]
        grant_types=["authorization_code", "refresh_token"],
        response_types=["code"],
        token_endpoint_auth_method="none",  # public client (PKCE), no client secret
        scope=scopes,
    )


def build_oauth_provider(
    sid: str,
    server_url: str,
    redirect_uri: str,
    *,
    scopes: str = DEFAULT_SCOPES,
    redirect_handler: Callable[[str], Awaitable[None]],
    callback_handler: Callable[[], Awaitable[tuple[str, str | None]]],
) -> OAuthClientProvider:
    """Construct the SDK OAuth provider (an ``httpx.Auth``) for one MCP server, wired to
    keychain storage. Pass the result as ``auth=`` to ``streamablehttp_client``."""
    egress.assert_public_url(server_url)
    return OAuthClientProvider(
        server_url=server_url,
        client_metadata=build_client_metadata(redirect_uri, scopes),
        storage=KeychainTokenStorage(sid),
        redirect_handler=redirect_handler,
        callback_handler=callback_handler,
    )


class ReauthorizationRequired(Exception):
    """Raised when a background MCP call needs a fresh interactive authorize (no valid
    token and none refreshable). The UI should prompt the user to reconnect."""


async def _reauth_redirect(_url: str) -> None:
    raise ReauthorizationRequired(
        "This connector needs to be re-authorized. Open its OAuth login from Connectors.")


async def _reauth_callback() -> tuple[str, str | None]:
    raise ReauthorizationRequired("This connector needs to be re-authorized.")


def background_provider(sid: str, server_url: str) -> OAuthClientProvider:
    """An OAuth provider for non-interactive use (discovery / tool calls). It attaches a
    stored token and refreshes it silently; if interactive re-auth is unavoidable it
    raises ReauthorizationRequired instead of trying to pop a browser on the backend."""
    egress.assert_public_url(server_url)
    return OAuthClientProvider(
        server_url=server_url,
        client_metadata=build_client_metadata("http://127.0.0.1/callback"),
        storage=KeychainTokenStorage(sid),
        redirect_handler=_reauth_redirect,
        callback_handler=_reauth_callback,
    )


def open_in_browser(url: str) -> None:
    """Open an authorization URL in the user's default browser (best-effort)."""
    import webbrowser
    with contextlib.suppress(Exception):
        webbrowser.open(url)


def make_redirect_handler(open_url: Callable[[str], None]) -> Callable[[str], Awaitable[None]]:
    """An async redirect_handler that opens the authorization URL via ``open_url``."""
    async def _redirect(url: str) -> None:
        egress.assert_public_url(url)
        open_url(url)
    return _redirect


def interactive_provider(
    sid: str,
    server_url: str,
    redirect_uri: str,
    *,
    open_url: Callable[[str], None] = open_in_browser,
    callback: Callable[[], Awaitable[tuple[str, str | None]]],
) -> OAuthClientProvider:
    """An OAuth provider for the interactive authorize flow: its redirect_handler opens
    the authorization URL in the browser and its callback_handler awaits the code from a
    loopback listener. ``redirect_uri`` must match the one the listener is serving."""
    egress.assert_public_url(server_url)
    return OAuthClientProvider(
        server_url=server_url,
        client_metadata=build_client_metadata(redirect_uri),
        storage=KeychainTokenStorage(sid),
        redirect_handler=make_redirect_handler(open_url),
        callback_handler=callback,
    )


_CALLBACK_HTML = (
    "<!doctype html><html><head><meta charset='utf-8'><title>Connected</title></head>"
    "<body style='font-family:system-ui;padding:3rem;text-align:center'>"
    "<h2>Authorized ✓</h2><p>You can close this window and return to "
    "Open Claude Desktop.</p></body></html>"
)


class LoopbackAuthCatcher:
    """One-shot ``127.0.0.1`` listener that captures the OAuth redirect.

    Usage::

        catcher = LoopbackAuthCatcher()
        redirect_uri = await catcher.start()          # give this to the provider
        # ... open the authorize URL; user approves; browser hits redirect_uri ...
        code, state = await catcher.wait()            # the callback_handler
        await catcher.close()

    It parses only the request line (``GET /callback?code=…&state=… HTTP/1.1``) — enough
    to recover the authorization code — and always replies with a friendly page.
    """

    def __init__(self, host: str = "127.0.0.1", path: str = "/callback") -> None:
        self._host = host
        self._path = path
        self._server: asyncio.AbstractServer | None = None
        self._future: asyncio.Future[tuple[str, str | None]] = asyncio.get_event_loop().create_future()
        self.redirect_uri = ""

    async def start(self) -> str:
        self._server = await asyncio.start_server(self._handle, self._host, 0)
        port = self._server.sockets[0].getsockname()[1]
        self.redirect_uri = f"http://{self._host}:{port}{self._path}"
        return self.redirect_uri

    async def _handle(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        try:
            request_line = await reader.readline()
            target = ""
            parts = request_line.decode("latin-1").split(" ")
            if len(parts) >= 2:
                target = parts[1]
            qs = parse_qs(urlsplit(target).query)
            code = (qs.get("code") or [""])[0]
            state = (qs.get("state") or [None])[0]
            body = _CALLBACK_HTML.encode("utf-8")
            writer.write(b"HTTP/1.1 200 OK\r\nContent-Type: text/html; charset=utf-8\r\n"
                         b"Content-Length: " + str(len(body)).encode() + b"\r\n"
                         b"Connection: close\r\n\r\n" + body)
            with contextlib.suppress(Exception):
                await writer.drain()
            if code and not self._future.done():
                self._future.set_result((code, state))
        finally:
            with contextlib.suppress(Exception):
                writer.close()

    async def wait(self, timeout: float = 300.0) -> tuple[str, str | None]:
        return await asyncio.wait_for(self._future, timeout=timeout)

    async def close(self) -> None:
        if self._server is not None:
            self._server.close()
            with contextlib.suppress(Exception):
                await self._server.wait_closed()


def summarize_tokens(sid: str) -> dict:
    """Non-secret status of a connector's OAuth state (for the UI): authorized?, scope,
    and whether a refresh token is held. Never returns the access token itself."""
    raw = secrets.get_secret_store().get(_tokens_key(sid))
    if not raw:
        return {"authorized": False}
    try:
        data = json.loads(raw)
    except Exception:
        return {"authorized": False}
    return {"authorized": True, "scope": data.get("scope", ""),
            "has_refresh": bool(data.get("refresh_token"))}
