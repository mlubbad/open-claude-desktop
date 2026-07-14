"""Single source of truth for env-driven configuration (parity with the
pre-refactor app.py + aj360_app/core.py constants)."""
import hashlib
import os
import sys
from pathlib import Path

# Product name, surfaced in user-facing messages (e.g. marketplace hints).
APP_NAME = "Open Claude Desktop"
# Backend API version (FastAPI app version + the diagnostics snapshot).
BACKEND_VERSION = "0.4.0"


# --- paths (data dir) ---
def _default_data_root() -> Path:
    """Where all user data lives (DB, projects, chroma, settings, cowork/schedules).

    Precedence:
      1. AJ360_DATA_DIR — set by the desktop shell to a stable per-user directory.
      2. Frozen build (PyInstaller) — a per-OS user-data dir. `__file__` here resolves
         INSIDE the ephemeral _MEIPASS extraction dir, so deriving the root from it
         would scatter data into OS temp and lose everything on every restart.
      3. Source/dev — the repo root two levels up from this package (stable).
    """
    env = os.getenv("AJ360_DATA_DIR")
    if env:
        return Path(env)  # verbatim (no .resolve()), matching the historical override
    if getattr(sys, "frozen", False):
        home = Path.home()
        if sys.platform == "win32":
            base = Path(os.getenv("APPDATA") or home / "AppData" / "Roaming")
        elif sys.platform == "darwin":
            base = home / "Library" / "Application Support"
        else:
            base = Path(os.getenv("XDG_DATA_HOME") or home / ".local" / "share")
        return base / "OpenClaudeDesktop"
    return Path(__file__).resolve().parents[2]


REPO_ROOT = _default_data_root()
REPO_ROOT.mkdir(parents=True, exist_ok=True)
PROJECTS_DIR = Path(os.getenv("PROJECTS_DIR", str(REPO_ROOT / "projects")))
KNOWLEDGE_DIR = Path(os.getenv("KNOWLEDGE_DIR", str(REPO_ROOT / "knowledge")))
CHROMA_PATH = os.getenv("CHROMA_PATH", str(REPO_ROOT / "chroma_db"))
SKILLS_DIR = Path(os.getenv("SKILLS_DIR", str(REPO_ROOT / "skills")))
PLUGINS_DIR = Path(os.getenv("PLUGINS_DIR", str(REPO_ROOT / "plugins")))
# Bundled, vetted plugin catalog the marketplace installs FROM (into PLUGINS_DIR).
MARKETPLACE_DIR = Path(os.getenv("MARKETPLACE_DIR", str(REPO_ROOT / "content" / "marketplace")))
# User-added marketplace sources: git repos cloned locally that contribute installable
# plugins alongside the bundled catalog, plus the JSON registry of added sources.
MARKETPLACE_SOURCES_DIR = Path(os.getenv(
    "MARKETPLACE_SOURCES_DIR", str(REPO_ROOT / "content" / "marketplace_sources")))
MARKETPLACE_SOURCES_FILE = Path(os.getenv(
    "MARKETPLACE_SOURCES_FILE", str(MARKETPLACE_SOURCES_DIR / "sources.json")))
# A remote marketplace runs third-party plugin CODE on this machine. On by default (the
# desktop app gates it behind an explicit warning); ops can hard-disable with "0".
MARKETPLACE_ALLOW_REMOTE = os.getenv(
    "MARKETPLACE_ALLOW_REMOTE", "1").strip().lower() in ("1", "true", "yes")
MARKETPLACE_CLONE_TIMEOUT_SEC = int(os.getenv("MARKETPLACE_CLONE_TIMEOUT_SEC", "90"))
MARKETPLACE_MAX_SOURCE_BYTES = int(os.getenv("MARKETPLACE_MAX_SOURCE_MB", "40")) * 1024 * 1024
# Ceiling on how many repository sources can be registered (bounds aggregate disk use).
MARKETPLACE_MAX_SOURCES = int(os.getenv("MARKETPLACE_MAX_SOURCES", "50"))

# --- BigQuery (optional connector, Phase 2) ---
PROJECT_ID = os.getenv("GCP_PROJECT_ID", "")
# Explicit BIGQUERY_ENABLED wins; otherwise auto-on when a GCP project is set, so
# existing analytics deployments keep working and a fresh install is a pure assistant.
_bq_env = os.getenv("BIGQUERY_ENABLED")
BIGQUERY_ENABLED = (_bq_env.strip().lower() in ("1", "true", "yes")
                    if _bq_env is not None else bool(PROJECT_ID))
_GB = 1024 ** 3
MAX_BYTES_BILLED = int(float(os.getenv("MAX_BYTES_BILLED_GB", "100")) * _GB)
QUERY_TIMEOUT_SEC = int(os.getenv("QUERY_TIMEOUT_SEC", "300"))
MAX_RETURN_ROWS = 50
MAX_STORED_ROWS = 5000
MAX_COLS_PER_CARD = 200
MAX_TABLE_ROWS_UI = 50
CATALOG_DATASETS = [d.strip() for d in os.getenv(
    "CATALOG_DATASETS",
    "aj360,aj360_platform,aj360_search_analytics,al_jazeera_data_models,"
    "aj360_ds,aj360_monitoring,aj360_marts,aj360_acquisition_analytics"
).split(",") if d.strip()]
_CATALOG_VERSION = hashlib.md5(",".join(sorted(CATALOG_DATASETS)).encode()).hexdigest()[:12]
_CATALOG_VERSION_FILE = KNOWLEDGE_DIR / ".catalog_version"
GENERIC_COLS = {
    "date", "name", "value", "type", "key", "status", "id", "count", "total",
    "country", "city", "region", "month", "week", "weekday", "source", "medium",
    "device", "category", "title", "description", "label", "url", "hour", "day",
}

# --- models ---
AGENT_MODEL = os.getenv("AGENT_MODEL", os.getenv("PLANNER_MODEL", "glm-4-plus"))
FLASH_MODEL = os.getenv("FLASH_MODEL", "glm-4-flash")
VISION_MODEL = os.getenv("VISION_MODEL", "glm-4v-plus")
_glm_default = f"{AGENT_MODEL},glm-4.5-air,glm-4-flash,glm-4-long"
GLM_MODELS = list(dict.fromkeys(
    m.strip() for m in os.getenv("GLM_MODELS", _glm_default).split(",") if m.strip()))

# --- effort + settings ---
EFFORT_LEVELS = ["Low", "Medium", "High", "Extra", "Max"]
# Claude-style "Extended thinking" levels — each maps to real backend behaviour
# (steps cap + planning/verification passes + temperature) in agent.EFFORT.
EFFORT_DESCRIPTIONS = {
    "Low": "Fast, direct answers",
    "Medium": "A little more checking",
    "High": "Plans before answering",
    "Max": "Plans, then self-verifies",
}
DEFAULT_SETTINGS = {"model": AGENT_MODEL,
                    "provider": os.getenv("LLM_PROVIDER", "zhipu"),
                    "effort": "High", "theme": "light", "profile": {},
                    # Web-search backend. "searxng" (privacy-respecting, self-hostable,
                    # JSON API — the recommended free/open-source option; set searxng_url)
                    # falls back to the keyless "ddg" HTML endpoint when unset/unreachable.
                    "search_provider": os.getenv("SEARCH_PROVIDER", "ddg"),
                    "searxng_url": os.getenv("SEARXNG_URL", ""),
                    # Code-execution engine for the `code_execution` tool:
                    #   "auto"   — Docker's isolated sandbox when available, else a jailed
                    #              local run on this device (resource-limited). [default]
                    #   "docker" — Docker only (feature unavailable without a container runtime).
                    #   "local"  — always run locally on this device (no container).
                    #   "off"    — code execution disabled.
                    # Every run is still gated by the HITL approval prompt.
                    "code_execution": os.getenv("CODE_EXECUTION_MODE", "auto"),
                    # How much the agent asks before acting (HITL autonomy):
                    #   "strict" — ask before EVERY tool (approve each step)
                    #   "ask"    — ask before sensitive actions only (code/shell/files/DB) [default]
                    #   "auto"   — autonomous: never ask (auto-pilot)
                    "permission_mode": os.getenv("PERMISSION_MODE", "ask"),
                    # Memory: let the agent search PAST conversations mid-turn
                    # (the search_past_chats tool). Local + read-only; on by default.
                    "memory_search": True,
                    # Global autonomy kill-switch. When True, no NEW unattended work
                    # starts — scheduled automations don't fire and Cowork refuses new
                    # tasks — and flipping it on cancels any Cowork runs in flight. A
                    # panic button for a misbehaving/expensive autonomous run.
                    "autonomy_paused": False,
                    # Which models each provider shows in the chat model picker
                    # ({provider_id: [model, ...]}). Empty/missing = the picker's
                    # default (the first few of the provider's catalog).
                    "visible_models": {},
                    # User customisation of each provider's model list ({provider_id:
                    # [model, ...]}): custom_models are names the user typed in (beyond the
                    # built-in catalog); hidden_models are catalog entries they removed.
                    # The effective list a provider shows is (custom ∪ catalog) − hidden.
                    "custom_models": {},
                    "hidden_models": {},
                    # Opik observability (opt-in; free/open-source, self-hostable).
                    # When enabled, every agent turn is mirrored into an Opik trace
                    # (tool spans, thinking phases, usage) by ocd_core.opik_tracing —
                    # a pass-through event tap, so it can never block a turn.
                    #   opik_mode: "local" (self-hosted URL) | "cloud" (comet.com/opik).
                    # The API key is NEVER stored here — it lives in the OS keychain
                    # (ocd_core.secrets), set through the /observability/key endpoint,
                    # with the OPIK_API_KEY env var as a fallback.
                    "opik_enabled": os.getenv("OPIK_ENABLED", "").lower() in ("1", "true"),
                    "opik_mode": os.getenv("OPIK_MODE", "local"),
                    "opik_url": os.getenv("OPIK_URL_OVERRIDE", ""),
                    "opik_project": os.getenv("OPIK_PROJECT_NAME", "open-claude-desktop"),
                    "opik_workspace": os.getenv("OPIK_WORKSPACE", "")}
OPIK_MODES = ("local", "cloud")
THEME_CHOICES = ("system", "light", "dark")
SEARCH_PROVIDERS = ("ddg", "searxng")
CODE_EXECUTION_MODES = ("auto", "docker", "local", "off")
# User-selectable HITL autonomy levels (plan mode is a separate per-turn toggle).
PERMISSION_MODE_CHOICES = ("strict", "ask", "auto")
SETTINGS_FILE = REPO_ROOT / "settings.json"

# --- projects / conversations ---
PROJECT_CAPACITY_BYTES = int(os.getenv("PROJECT_CAPACITY_MB", "50")) * 1024 * 1024
CONV_MAX_MESSAGES = int(os.getenv("CONV_MAX_MESSAGES", "400"))
GENERAL_ID = "general"
GENERAL_NAME = "General"

# --- agent-assisted connector auth (host CLI login flows) ---
# The browser-consent step is human-paced, so allow a generous window before the
# login command is considered timed out. Set AUTH_FLOWS_ENABLED=0 to hard-disable.
AUTH_FLOW_TIMEOUT_SEC = int(os.getenv("AUTH_FLOW_TIMEOUT_SEC", "300"))
AUTH_FLOWS_ENABLED = os.getenv("AUTH_FLOWS_ENABLED", "1").strip().lower() in ("1", "true", "yes")

# Discovery timeout for the INTERACTIVE "add MCP server" path (also used by Retry).
# Bounded so a hung server can't tie up the request forever, but generous enough for
# a first-run cold start: `npx`/`uvx` servers download their package and `docker run`
# may pull an image on the first launch, which routinely takes 30-60s+. On timeout the
# server registers as errored and the card's Retry re-runs discovery (usually fast the
# second time — the download is cached).
MCP_ADD_TIMEOUT_SEC = int(os.getenv("MCP_ADD_TIMEOUT_SEC", "90"))

# --- rate limiting (salvaged from app.py) ---
RATE_LIMIT_QUERIES = int(os.getenv("RATE_LIMIT_QUERIES", "20"))
RATE_LIMIT_WINDOW_SEC = int(os.getenv("RATE_LIMIT_WINDOW_SEC", "60"))
# H1: throttle login attempts (per client) to stop unlimited password brute force.
LOGIN_RATE_LIMIT = int(os.getenv("LOGIN_RATE_LIMIT", "8"))
LOGIN_RATE_WINDOW_SEC = int(os.getenv("LOGIN_RATE_WINDOW_SEC", "300"))

# --- audit log (salvaged from app.py) ---
AUDIT_LOG = os.getenv("AUDIT_LOG", "./logs/agent_audit.jsonl")
AUDIT_LOG_MAX_BYTES = int(os.getenv("AUDIT_LOG_MAX_BYTES", str(10 * 1024 * 1024)))
AUDIT_LOG_BACKUPS = int(os.getenv("AUDIT_LOG_BACKUPS", "5"))

# --- write posture (kept; intentionally aj360-prefixed per project memory) ---
ALLOW_WRITES = os.getenv("AJ360_ALLOW_WRITES", "false").strip().lower() in ("1", "true", "yes")

# --- interactive tool permissions (HITL) ---
# auto = no prompts (default), ask = prompt for sensitive tools, strict = prompt for all.
PERMISSION_MODE = os.getenv("PERMISSION_MODE", "auto").strip().lower()
PERMISSION_TIMEOUT_SEC = int(os.getenv("PERMISSION_TIMEOUT_SEC", "300"))

# --- autonomy guardrails (bound runaway / autonomous spend) ---
# The EFFORT step cap bounds a single turn's main loop; these bound the two amplifiers
# it does NOT: subagent fan-out, and (as a backstop) the turn's total reported tokens.
# Without them, a delegated/scheduled run that loops or fans out indefinitely bills the
# user's BYOK key with no ceiling.
MAX_SUBAGENTS_PER_TURN = int(os.getenv("OCD_MAX_SUBAGENTS", "8"))
# Once a turn's reported (input+output) tokens cross this, the loop stops opening new
# work and lands on a final answer via the normal finalize path. Generous — a normal
# turn is a few thousand tokens; only a genuine runaway trips it. 0 disables the backstop.
# Reported tokens are best-effort, so this only engages for providers that report usage.
TURN_TOKEN_BUDGET = int(os.getenv("OCD_TURN_TOKEN_BUDGET", "1000000"))
# Don't launch a scheduled automation if its previous run is still active (a slow task on
# a short interval would otherwise stack copies of itself). On by default.
SCHEDULER_SKIP_OVERLAP = os.getenv("OCD_SCHEDULER_SKIP_OVERLAP", "1").strip().lower() \
    in ("1", "true", "yes")
