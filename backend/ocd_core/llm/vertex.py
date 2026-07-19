"""Vertex AI client builder — the ADC-authenticated OpenAI-compatible backend.

Vertex serves the same chat.completions surface as every other provider
(`https://{loc}-aiplatform.googleapis.com/v1beta1/projects/{p}/locations/{loc}/
endpoints/openapi`), but authenticates with SHORT-LIVED OAuth2 bearer tokens
(~1 hour) instead of a long-lived API key. So the client here comes in two
flavours:

  * a pasted/env token (BYOK box or VERTEX_AI_ACCESS_TOKEN) — used verbatim, no
    refresh; it simply expires when Google says so, and
  * Application Default Credentials — the hands-off path: the token is minted
    and refreshed from ADC (gcloud login or a service account) before calls,
    Google's documented wrapper pattern for the OpenAI libraries.

The GCP project and location come from env (VERTEX_AI_* first so Vertex can be
configured independently of the BigQuery connector's GCP_PROJECT_ID), falling
back to the project ADC itself reports. google-auth is already a backend
dependency (BigQuery), so ADC costs no extra install.
"""
from __future__ import annotations

import os
import threading

from .client import LLMConfigError

_SCOPES = ("https://www.googleapis.com/auth/cloud-platform",)
_PROJECT_ENVS = ("VERTEX_AI_PROJECT", "GOOGLE_CLOUD_PROJECT", "GCP_PROJECT_ID")
_LOCATION_ENVS = ("VERTEX_AI_LOCATION", "GOOGLE_CLOUD_LOCATION")
DEFAULT_LOCATION = "global"

_NEED_PROJECT = (
    "Vertex AI needs a GCP project: set VERTEX_AI_PROJECT (or GOOGLE_CLOUD_PROJECT), "
    "and optionally VERTEX_AI_LOCATION (default 'global').")
_NEED_CREDS = (
    "No Google Cloud credentials for Vertex AI. Run 'gcloud auth application-default "
    "login' (or point GOOGLE_APPLICATION_CREDENTIALS at a service-account key), or "
    "paste a short-lived access token ('gcloud auth print-access-token') as the "
    "provider key.")


def _first_env(names: tuple[str, ...]) -> str | None:
    for name in names:
        val = (os.getenv(name) or "").strip()
        if val:
            return val
    return None


def resolve_project_location() -> tuple[str | None, str]:
    """(project, location) from env; project may be None (ADC can still supply it)."""
    return _first_env(_PROJECT_ENVS), _first_env(_LOCATION_ENVS) or DEFAULT_LOCATION


def base_url_for(project: str, location: str) -> str:
    """The OpenAI-compatible endpoint for a project/location ('global' has no
    regional host prefix)."""
    host = ("aiplatform.googleapis.com" if location == "global"
            else f"{location}-aiplatform.googleapis.com")
    return (f"https://{host}/v1beta1/projects/{project}"
            f"/locations/{location}/endpoints/openapi")


def _adc_credentials():
    """ADC (credentials, default_project) with config errors turned actionable."""
    try:
        import google.auth
        from google.auth.exceptions import DefaultCredentialsError
    except ImportError as e:  # pragma: no cover - google-auth ships with the backend
        raise LLMConfigError(
            "Vertex AI's ADC path needs the google-auth package "
            "(pip install google-auth) — or paste an access token instead.") from e
    try:
        return google.auth.default(scopes=list(_SCOPES))
    except DefaultCredentialsError as e:
        raise LLMConfigError(_NEED_CREDS) from e


class _ADCRefreshingClient:
    """An OpenAI client whose bearer token is minted from ADC and refreshed when
    stale — checked on each `.chat` / `.models` access, so a client cached across
    the token's ~1 h lifetime keeps working. Attribute shape matches the plain
    client (`chat`, `models`, `base_url`) — the only surface the app uses."""

    def __init__(self, base_url: str, credentials):
        from openai import OpenAI
        self._creds = credentials
        self._lock = threading.Lock()
        self._client = OpenAI(base_url=base_url, api_key="adc-pending")

    def _fresh(self):
        with self._lock:
            if not self._creds.valid:
                from google.auth.transport.requests import Request
                self._creds.refresh(Request())
            # The SDK reads .api_key per request, so updating it takes effect
            # on the next call (Google's documented refresher pattern).
            self._client.api_key = self._creds.token
        return self._client

    @property
    def chat(self):
        return self._fresh().chat

    @property
    def models(self):
        return self._fresh().models

    @property
    def base_url(self):
        return self._client.base_url


def build_client(api_key: str | None):
    """The Vertex client: pasted/env token verbatim, else ADC with auto-refresh.

    Raises LLMConfigError with a fix-it message when the project or credentials
    can't be resolved — surfaced verbatim by the settings card's Test button.
    """
    project, location = resolve_project_location()
    if api_key:
        if not project:
            raise LLMConfigError(_NEED_PROJECT)
        from openai import OpenAI
        return OpenAI(base_url=base_url_for(project, location), api_key=api_key)
    creds, adc_project = _adc_credentials()
    project = project or (adc_project or "").strip() or None
    if not project:
        raise LLMConfigError(_NEED_PROJECT)
    return _ADCRefreshingClient(base_url_for(project, location), creds)
