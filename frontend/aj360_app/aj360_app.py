"""AJ360 — Projects UI built in Reflex (Claude-Desktop-style workspace).

Thin shell: assembles the app and registers pages. All UI components live in
``aj360_app.components`` (split out in Phase 4 Task 6).
"""
import reflex as rx

from .state import AppState
from .auth import AuthState, login_page
from .components.project_grid import dashboard, chats_dashboard
from .components.workspace_panels import workspace, cowork_page
from .components.artifact_viewer import code_page, artifacts_page, connectors_page
from .components.settings import customize_page
from .components.conversation import conversation_page


# --------------------------------------------------------------------------- #
#  App
# --------------------------------------------------------------------------- #
app = rx.App(
    stylesheets=["/theme.css"],
    style={"fontFamily": "var(--default-font-family)"},
)
# C4: /login is the only ungated page; every other page redirects to it via
# AuthState.require_login (runs first in each on_load) when not authenticated.
app.add_page(login_page, route="/login", on_load=AuthState.redirect_if_authed,
             title="Open Claude Desktop · Sign in")
app.add_page(dashboard, route="/",
             on_load=[AuthState.require_login, AppState.load_dashboard, AppState.check_backend],
             title="Open Claude Desktop · Projects")
app.add_page(workspace, route="/project/[pid]",
             on_load=[AuthState.require_login, AppState.load_workspace],
             title="Open Claude Desktop · Project")
app.add_page(conversation_page, route="/project/[pid]/c/[cid]",
             on_load=[AuthState.require_login, AppState.load_conversation],
             title="Open Claude Desktop · Chat")
app.add_page(chats_dashboard, route="/chats",
             on_load=[AuthState.require_login, AppState.load_chats],
             title="Open Claude Desktop · Chats")
app.add_page(customize_page, route="/customize",
             on_load=[AuthState.require_login, AppState.load_customize],
             title="Open Claude Desktop · Customize")
app.add_page(code_page, route="/code",
             on_load=[AuthState.require_login, AppState.load_code],
             title="Open Claude Desktop · Code")
app.add_page(artifacts_page, route="/artifacts",
             on_load=[AuthState.require_login, AppState.load_artifacts],
             title="Open Claude Desktop · Artifacts")
app.add_page(cowork_page, route="/cowork",
             on_load=[AuthState.require_login, AppState.load_cowork],
             title="Open Claude Desktop · General")
app.add_page(connectors_page, route="/connectors",
             on_load=[AuthState.require_login, AppState.load_connectors_page],
             title="Open Claude Desktop · Connectors")
