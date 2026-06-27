"""Single source of truth for env-driven configuration (parity with the
pre-refactor app.py + aj360_app/core.py constants)."""
import hashlib
import os
from pathlib import Path

# --- paths (data dir override) ---
REPO_ROOT = Path(os.getenv("AJ360_DATA_DIR", "")).resolve() if os.getenv("AJ360_DATA_DIR") \
    else Path(__file__).resolve().parents[2]
PROJECTS_DIR = Path(os.getenv("PROJECTS_DIR", str(REPO_ROOT / "projects")))
KNOWLEDGE_DIR = Path(os.getenv("KNOWLEDGE_DIR", str(REPO_ROOT / "knowledge")))
CHROMA_PATH = os.getenv("CHROMA_PATH", str(REPO_ROOT / "chroma_db"))
SKILLS_DIR = Path(os.getenv("SKILLS_DIR", str(REPO_ROOT / "skills")))
PLUGINS_DIR = Path(os.getenv("PLUGINS_DIR", str(REPO_ROOT / "plugins")))

# --- BigQuery ---
PROJECT_ID = os.getenv("GCP_PROJECT_ID", "ajgc-dig-jjc-prod-jawacloud-01")
_GB = 1024 ** 3
MAX_BYTES_BILLED = int(os.getenv("MAX_BYTES_BILLED_GB", "100")) * _GB
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
EFFORT_LEVELS = ["Low", "Medium", "High", "Max"]
DEFAULT_SETTINGS = {"model": AGENT_MODEL, "effort": "High", "theme": "light"}
SETTINGS_FILE = REPO_ROOT / "settings.json"

# --- projects / conversations ---
PROJECT_CAPACITY_BYTES = int(os.getenv("PROJECT_CAPACITY_MB", "50")) * 1024 * 1024
CONV_MAX_MESSAGES = int(os.getenv("CONV_MAX_MESSAGES", "400"))
GENERAL_ID = "general"
GENERAL_NAME = "General"

# --- rate limiting (salvaged from app.py) ---
RATE_LIMIT_QUERIES = int(os.getenv("RATE_LIMIT_QUERIES", "20"))
RATE_LIMIT_WINDOW_SEC = int(os.getenv("RATE_LIMIT_WINDOW_SEC", "60"))

# --- audit log (salvaged from app.py) ---
AUDIT_LOG = os.getenv("AUDIT_LOG", "./logs/agent_audit.jsonl")
AUDIT_LOG_MAX_BYTES = int(os.getenv("AUDIT_LOG_MAX_BYTES", str(10 * 1024 * 1024)))
AUDIT_LOG_BACKUPS = int(os.getenv("AUDIT_LOG_BACKUPS", "5"))

# --- write posture (kept; intentionally aj360-prefixed per project memory) ---
ALLOW_WRITES = os.getenv("AJ360_ALLOW_WRITES", "").lower() in ("1", "true", "yes")
