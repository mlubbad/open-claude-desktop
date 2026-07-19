# Google Gemini + Vertex AI providers — design

Date: 2026-07-20 · Status: implemented same-day (autonomous session; user asked for
"Gemini and Vertex AI models in Models & keys, backend and frontend")

## Goal

Google's models become first-class BYOK providers in the Models & keys dialog:

- **Google Gemini** — the consumer/AI-Studio API. A long-lived API key; the perfect
  fit for the existing BYOK card (paste key → test → pick model).
- **Vertex AI** — the GCP-side offering (project-scoped, IAM-governed, Model Garden
  ids like `google/gemini-3.5-flash`). Auth is *not* a pasteable long-lived key, so
  its card needs one small extension (an optional token box + a setup hint).

## Facts the design rests on (verified 2026-07-20)

- Gemini exposes an OpenAI-compatible surface at
  `https://generativelanguage.googleapis.com/v1beta/openai` — chat completions,
  streaming, tools, vision, `reasoning_effort`, and `GET /models` (bare ids such as
  `gemini-3.5-flash`) all work with `Authorization: Bearer <API key>`
  (https://ai.google.dev/gemini-api/docs/openai).
- Vertex AI's OpenAI-compatible surface lives at
  `https://{loc}-aiplatform.googleapis.com/v1beta1/projects/{project}/locations/{loc}/endpoints/openapi`
  (`aiplatform.googleapis.com` + `locations/global` for the global endpoint). It
  accepts ONLY OAuth2 bearer tokens (~1 h lifetime, from ADC); express-mode API keys
  do not work on this surface. Google documents a refresh-before-call wrapper
  (docs.cloud.google.com/vertex-ai/generative-ai/docs/migrate/openai/auth-and-credentials).
- `google-auth` is already a backend dependency (BigQuery connector), so ADC support
  costs no new install.
- Current model line-up (ai.google.dev/gemini-api/docs/models): `gemini-3.5-flash`
  (flagship, stable), `gemini-3.1-pro-preview`, `gemini-3.1-flash-lite`,
  `gemini-2.5-pro/flash/flash-lite` (stable).

## Approaches considered for Vertex auth

1. **ADC with auto-refresh, pasted-token override** *(chosen)* — no key required:
   the client wraps ADC credentials and refreshes the bearer before each call
   (Google's documented pattern). A user who prefers not to set up ADC can still
   paste a short-lived token (`gcloud auth print-access-token`) into the normal key
   box; it is used verbatim. Project/location come from env
   (`VERTEX_AI_PROJECT` → `GOOGLE_CLOUD_PROJECT` → `GCP_PROJECT_ID` → the ADC
   default project; `VERTEX_AI_LOCATION` → `GOOGLE_CLOUD_LOCATION` → `global`).
2. Express-mode API key — rejected: express keys don't work against the
   OpenAI-compatible endpoint this app drives everything through, and express mode
   covers only a model subset.
3. Native `google-genai` SDK adapter (anthropic_native-style) — rejected for now:
   a whole second call-shape adapter for capabilities the compat endpoint already
   provides; revisit only if Vertex-only features (context caching etc.) are wanted.

## Changes

Backend (`backend/ocd_core/llm/`):

- `providers.py` — `Provider` gains two backward-compatible fields:
  `key_optional: bool = False` (render a key box even though `requires_key=False`;
  the secret is an optional override) and `key_hint: str = ""` (one-line setup hint
  for the card). Registry gains `gemini` (after `anthropic`) and `vertex`
  (`requires_key=False`, `key_optional=True`, models `google/`-prefixed,
  `base_url=None` — computed per project/location in `vertex.py`).
- `vertex.py` (new) — project/location resolution, base-URL builder
  (global vs regional), and `build_vertex_client(api_key)`: pasted/env token →
  plain `OpenAI` client with that bearer; otherwise an ADC-backed proxy that
  refreshes `credentials.token` when stale and delegates `.chat` / `.models` to an
  inner `OpenAI` client. Actionable `LLMConfigError`s: missing project → name the
  env vars; no ADC → name `gcloud auth application-default login` and the
  paste-a-token alternative.
- `client.py` — `get_client` branches `pid == "vertex"` to the builder (mirrors the
  existing `anthropic` branch).
- `keys.py` — `has_key()` for `key_optional` providers reports actual key presence
  (drives the badge: "token set" vs ADC) instead of the blanket `True`; usability
  is untouched (`requires_key=False` paths never hard-require a key).
- `catalog.py` — rules: `gemini-3` and `gemini-2.5` → 1 M ctx / 65 536 out, vision
  + tools + reasoning; generic `gemini` → 1 M / 8 192, vision + tools. The existing
  bare-name normalisation strips the `google/` prefix, so one rule set serves both
  providers. Reasoning=True automatically wires the agent's `reasoning_effort`
  passthrough (best-effort with a clean no-extras retry).
- `app/routes/providers.py` — `_provider_view` adds `key_optional` + `key_hint`.

Desktop (`desktop/src/`):

- `api/client.ts` — `ProviderInfo` gains optional `key_optional` / `key_hint`.
- `components/settings/ProvidersPage.tsx` — key box renders when
  `requires_key || key_optional` (placeholder "… access token (optional)");
  badge for key-optional providers: "token set" / "cloud auth (ADC)"; `key_hint`
  renders as a muted line under the key box. Everything else (chips, eye, add
  model, Load models, Test) is already provider-agnostic.
- `state/modelMeta.ts` — descriptor regexes learn Gemini names (cosmetic).

No changes needed to the model picker, retry menu, settings persistence, or the
agent loop: `resolve_turn_client(provider="vertex", model="google/…")` passes the
model verbatim (established NIM/OpenRouter behaviour), and `probe_provider`'s
completion fallback already covers Vertex's missing `GET /models`.

## Error handling

- Vertex misconfiguration surfaces through the card's Test button as the
  `LLMConfigError` text (probe returns `(False, detail)`).
- "Load models" on Vertex returns `ok=False` + detail (endpoint has no /models);
  the card ships a starter catalog and accepts typed additions, same as before.
- Expired pasted token → provider 401 text in Test; the hint line says tokens are
  short-lived and ADC is the hands-off path.

## Testing

- `test_llm_providers.py` — registry/contract additions ride the existing
  invariant tests; new cases for `split_model` with the new ids and key-optional
  `has_key` semantics.
- `test_llm_vertex.py` (new) — env-chain resolution, global vs regional URL,
  token-override client, ADC refresh path (fake credentials), missing
  project/ADC error messages.
- `test_providers_route.py` — view exposes the two new fields.
- `ProvidersPage.test.tsx` — key-optional card renders the optional token box,
  hint, and ADC badge; a required-key card is unchanged.
- Full backend pytest + ruff, desktop typecheck + vitest + build.
