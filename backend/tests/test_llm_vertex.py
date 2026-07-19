"""Google providers: the Gemini registry entry and the Vertex AI ADC/token client.

Gemini is a plain OpenAI-compatible provider (long-lived API key). Vertex AI is the
special one: per-project/location base URL and short-lived OAuth bearers — pasted
token used verbatim, else ADC credentials minted and refreshed by llm.vertex.
"""
import pytest
from ocd_core import llm, secrets
from ocd_core.llm import catalog
from ocd_core.llm import client as llm_client
from ocd_core.llm import keys as llm_keys
from ocd_core.llm import vertex


@pytest.fixture(autouse=True)
def _clean(monkeypatch):
    # Deterministic: in-memory secret store, and none of the Google env leaking in.
    monkeypatch.setenv("OCD_SECRET_BACKEND", "memory")
    for env in ("VERTEX_AI_PROJECT", "GOOGLE_CLOUD_PROJECT", "GCP_PROJECT_ID",
                "VERTEX_AI_LOCATION", "GOOGLE_CLOUD_LOCATION",
                "VERTEX_AI_ACCESS_TOKEN", "GEMINI_API_KEY", "LLM_API_KEY",
                "GOOGLE_APPLICATION_CREDENTIALS"):
        monkeypatch.delenv(env, raising=False)
    secrets.reset_store()
    llm_client.reset_clients()
    yield
    secrets.reset_store()
    llm_client.reset_clients()


class _FakeCreds:
    """Stands in for google.auth ADC credentials: invalid until refreshed."""

    def __init__(self):
        self.token = None
        self.valid = False
        self.refreshes = 0

    def refresh(self, request):  # noqa: ARG002 - transport request unused
        self.refreshes += 1
        self.token = f"adc-tok-{self.refreshes}"
        self.valid = True


# ---- registry ---------------------------------------------------------------

def test_google_providers_registered():
    by_id = {p.id: p for p in llm.list_providers()}
    gemini, vertex_p = by_id["gemini"], by_id["vertex"]
    assert "generativelanguage.googleapis.com/v1beta/openai" in gemini.base_url
    assert gemini.requires_key and not gemini.key_optional
    assert gemini.default_model in gemini.models
    # Vertex: no required key (ADC), but the optional-token box + hint render.
    assert vertex_p.requires_key is False and vertex_p.key_optional is True
    assert vertex_p.key_hint
    assert vertex_p.default_model in vertex_p.models
    assert all(m.startswith("google/") for m in vertex_p.models)


def test_vertex_model_ids_do_not_split():
    # google/… is a publisher prefix, not a provider id — must reach Vertex intact.
    assert llm.split_model("google/gemini-2.5-flash") == (None, "google/gemini-2.5-flash")


# ---- capability catalog -----------------------------------------------------

def test_gemini_capabilities_cover_both_id_shapes():
    for model in ("gemini-3.5-flash", "google/gemini-3.5-flash"):
        caps = catalog.capabilities(model)
        assert caps.context_window == 1_000_000
        assert caps.vision and caps.tools and caps.reasoning
    caps25 = catalog.capabilities("google/gemini-2.5-pro")
    assert caps25.reasoning and caps25.max_output == 65_536
    # Older/unknown gemini names hit the generic gemini rule: vision, no reasoning.
    legacy = catalog.capabilities("gemini-1.5-pro")
    assert legacy.vision and not legacy.reasoning


# ---- key semantics ----------------------------------------------------------

def test_vertex_has_key_reports_token_presence_not_usability():
    assert llm_keys.has_key("vertex") is False  # ADC default: no token stored
    llm_keys.set_api_key("vertex", "tok-x")
    assert llm_keys.has_key("vertex") is True
    llm_keys.delete_api_key("vertex")
    assert llm_keys.has_key("vertex") is False
    # Plain key-free locals keep the blanket True.
    assert llm_keys.has_key("ollama") is True


# ---- project/location + base URL -------------------------------------------

def test_project_env_precedence(monkeypatch):
    assert vertex.resolve_project_location() == (None, "global")
    monkeypatch.setenv("GCP_PROJECT_ID", "bq-proj")
    assert vertex.resolve_project_location()[0] == "bq-proj"
    monkeypatch.setenv("GOOGLE_CLOUD_PROJECT", "gcp-proj")
    assert vertex.resolve_project_location()[0] == "gcp-proj"
    monkeypatch.setenv("VERTEX_AI_PROJECT", "vertex-proj")
    monkeypatch.setenv("VERTEX_AI_LOCATION", "europe-west4")
    assert vertex.resolve_project_location() == ("vertex-proj", "europe-west4")


def test_base_url_global_vs_regional():
    assert vertex.base_url_for("p1", "global") == (
        "https://aiplatform.googleapis.com/v1beta1/projects/p1"
        "/locations/global/endpoints/openapi")
    assert vertex.base_url_for("p1", "us-central1").startswith(
        "https://us-central1-aiplatform.googleapis.com/")


# ---- client construction ----------------------------------------------------

def test_pasted_token_used_verbatim(monkeypatch):
    monkeypatch.setenv("GOOGLE_CLOUD_PROJECT", "proj-7")
    llm_keys.set_api_key("vertex", "tok-pasted")
    client = llm.get_client("vertex")
    assert client.api_key == "tok-pasted"
    assert "projects/proj-7/locations/global/endpoints/openapi" in str(client.base_url)


def test_env_token_fallback(monkeypatch):
    monkeypatch.setenv("GOOGLE_CLOUD_PROJECT", "proj-8")
    monkeypatch.setenv("VERTEX_AI_ACCESS_TOKEN", "tok-env")
    assert llm.get_client("vertex").api_key == "tok-env"


def test_token_without_project_is_actionable(monkeypatch):
    llm_keys.set_api_key("vertex", "tok-pasted")
    with pytest.raises(llm.LLMConfigError, match="VERTEX_AI_PROJECT"):
        llm.get_client("vertex")


def test_adc_client_refreshes_stale_tokens(monkeypatch):
    creds = _FakeCreds()
    import google.auth
    monkeypatch.setattr(google.auth, "default", lambda scopes=None: (creds, "adc-proj"))
    client = llm.get_client("vertex")
    # Project fell back to the one ADC reported; token minted on first use.
    assert "projects/adc-proj/" in str(client.base_url)
    _ = client.chat
    assert creds.refreshes == 1
    assert client._client.api_key == "adc-tok-1"
    _ = client.models          # still valid -> no extra refresh
    assert creds.refreshes == 1
    creds.valid = False        # simulate the ~1 h expiry
    _ = client.chat
    assert creds.refreshes == 2
    assert client._client.api_key == "adc-tok-2"


def test_no_adc_is_actionable(monkeypatch):
    import google.auth
    from google.auth.exceptions import DefaultCredentialsError

    def _no_adc(scopes=None):
        raise DefaultCredentialsError("no creds")

    monkeypatch.setattr(google.auth, "default", _no_adc)
    with pytest.raises(llm.LLMConfigError, match="gcloud auth application-default"):
        llm.get_client("vertex")
    # And the settings card's Test button gets the same guidance, not a stack trace.
    ok, detail = llm.probe_provider("vertex")
    assert ok is False and "gcloud" in detail
