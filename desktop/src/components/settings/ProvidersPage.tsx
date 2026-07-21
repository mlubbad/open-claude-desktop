import { useEffect, useState } from "react";

import { type ProviderInfo, providers, settings as settingsApi } from "../../api/client";
import { effectiveCatalog, pickerModels } from "../../state/modelMeta";
import { Icon } from "../Icon";

// Models & keys: BYOK providers, connection test, and a fully customisable per-provider
// model list — add any model name the endpoint accepts, remove ones you don't use, and
// choose which appear in the chat picker (the eye).

// "Load models" can pull hundreds of ids (NIM, Gemini). Above these thresholds the chip
// row gets a search box and is capped behind a "Show all" expander so the page stays
// scannable; search always filters the FULL catalog, and every chip action (pick / eye /
// remove / add) keeps operating on the full catalog, never just the visible slice.
export const MODEL_SEARCH_MIN = 10;
export const MODEL_CHIP_CAP = 24;

export function ProvidersPage({
  active,
  onPick,
}: {
  active: { provider: string; model: string };
  onPick: (provider: string, model: string) => void;
}) {
  const [list, setList] = useState<ProviderInfo[]>([]);
  const [listLoading, setListLoading] = useState(true);
  const [keyDraft, setKeyDraft] = useState<Record<string, string>>({});
  const [err, setErr] = useState<string | null>(null);
  const [probing, setProbing] = useState<string | null>(null);
  const [loading, setLoading] = useState<string | null>(null);
  const [probe, setProbe] = useState<Record<string, { ok: boolean; detail: string }>>({});
  // Per-provider models the chat picker shows ({} entry = the newest-few default).
  const [visible, setVisible] = useState<Record<string, string[]>>({});
  // Per-provider user customisation of the model list.
  const [custom, setCustom] = useState<Record<string, string[]>>({});
  const [hidden, setHidden] = useState<Record<string, string[]>>({});
  // The "add a model" input per provider.
  const [modelDraft, setModelDraft] = useState<Record<string, string>>({});
  // Big-catalog chip row state: the per-provider search needle + Show-all expansion.
  const [modelQuery, setModelQuery] = useState<Record<string, string>>({});
  const [expanded, setExpanded] = useState<Record<string, boolean>>({});

  async function refresh() {
    try {
      setList(await providers.list());
    } catch (e) {
      setErr(String(e));
    } finally {
      setListLoading(false);
    }
  }
  useEffect(() => {
    void refresh();
    settingsApi
      .get()
      .then((s) => {
        setVisible(s.visible_models ?? {});
        setCustom(s.custom_models ?? {});
        setHidden(s.hidden_models ?? {});
      })
      .catch(() => {});
  }, []);

  // The provider's effective model list: user additions first, then the built-in
  // catalog, minus the models the user removed.
  function catalogFor(p: ProviderInfo): string[] {
    const base = p.models.length ? p.models : [p.default_model].filter(Boolean);
    return effectiveCatalog(base, custom[p.id], hidden[p.id]);
  }

  // Is this model currently shown in the chat picker? (explicit selection, or the
  // newest-few default when the provider has no selection yet)
  function shown(p: ProviderInfo, m: string): boolean {
    return pickerModels(catalogFor(p), visible[p.id], "").includes(m);
  }

  // Toggle a model's picker visibility. The first toggle materializes the provider's
  // default into an explicit list; hiding the last visible model is a no-op.
  function toggleShown(p: ProviderInfo, m: string) {
    const cat = catalogFor(p);
    const cur = pickerModels(cat, visible[p.id], "");
    const next = cur.includes(m) ? cur.filter((x) => x !== m) : [...cur, m];
    if (next.length === 0) return;
    const all = { ...visible, [p.id]: cat.filter((x) => next.includes(x)) };
    setVisible(all);
    void settingsApi.save({ visible_models: all }).catch((e) => setErr(String(e)));
  }

  // Add a custom model name to a provider. Un-hides it if it was removed, records it as
  // custom when it's not a built-in, and surfaces it in the chat picker straight away.
  function addModel(p: ProviderInfo, raw: string) {
    const m = raw.trim();
    if (!m) return;
    const base = p.models ?? [];
    const cust = custom[p.id] ?? [];
    const hid = hidden[p.id] ?? [];
    const preCatalog = effectiveCatalog(base.length ? base : [p.default_model].filter(Boolean), cust, hid);
    const nextHidden = { ...hidden, [p.id]: hid.filter((x) => x !== m) };
    const nextCustom =
      base.includes(m) || cust.includes(m) ? custom : { ...custom, [p.id]: [...cust, m] };
    const nextVisible = { ...visible, [p.id]: Array.from(new Set([...pickerModels(preCatalog, visible[p.id], ""), m])) };
    setHidden(nextHidden);
    setCustom(nextCustom);
    setVisible(nextVisible);
    setModelDraft((d) => ({ ...d, [p.id]: "" }));
    void settingsApi
      .save({ custom_models: nextCustom, hidden_models: nextHidden, visible_models: nextVisible })
      .catch((e) => setErr(String(e)));
  }

  // Remove a model from a provider's list. A custom entry is deleted; a built-in catalog
  // entry is hidden (it can't be deleted from the shipped catalog). Either way it also
  // leaves the picker selection.
  function removeModel(p: ProviderInfo, m: string) {
    const base = p.models ?? [];
    const cust = custom[p.id] ?? [];
    const isCustom = cust.includes(m);
    const nextCustom = isCustom ? { ...custom, [p.id]: cust.filter((x) => x !== m) } : custom;
    const nextHidden =
      !isCustom && base.includes(m)
        ? { ...hidden, [p.id]: [...(hidden[p.id] ?? []), m] }
        : hidden;
    const nextVisible = visible[p.id]
      ? { ...visible, [p.id]: visible[p.id].filter((x) => x !== m) }
      : visible;
    setCustom(nextCustom);
    setHidden(nextHidden);
    setVisible(nextVisible);
    void settingsApi
      .save({ custom_models: nextCustom, hidden_models: nextHidden, visible_models: nextVisible })
      .catch((e) => setErr(String(e)));
  }

  // Pull the provider's live model catalog (GET /models) and merge new ids into the
  // provider's list. For a large/rotating catalog (e.g. NVIDIA NIM) this populates the
  // real, current models with one click instead of a guessed hardcoded set.
  async function loadModels(p: ProviderInfo) {
    setLoading(p.id);
    try {
      const res = await providers.availableModels(p.id);
      if (!res.ok) {
        setProbe((pr) => ({ ...pr, [p.id]: { ok: false, detail: res.detail || "Couldn't load models." } }));
        return;
      }
      const base = p.models ?? [];
      const cust = custom[p.id] ?? [];
      const have = new Set([...base, ...cust]);
      const fresh = res.models.filter((m) => m && !have.has(m));
      const nextCustom = fresh.length ? { ...custom, [p.id]: [...cust, ...fresh] } : custom;
      // Un-hide any returned models the user had removed, so a reload brings them back.
      const nextHidden = hidden[p.id]?.length
        ? { ...hidden, [p.id]: hidden[p.id].filter((m) => !res.models.includes(m)) }
        : hidden;
      setCustom(nextCustom);
      setHidden(nextHidden);
      setProbe((pr) => ({
        ...pr,
        [p.id]: { ok: true, detail: `Loaded ${res.models.length} models (${fresh.length} new).` },
      }));
      if (nextCustom !== custom || nextHidden !== hidden) {
        await settingsApi.save({ custom_models: nextCustom, hidden_models: nextHidden });
      }
    } catch (e) {
      setErr(String(e));
    } finally {
      setLoading(null);
    }
  }

  async function testProvider(id: string) {
    setProbing(id);
    try {
      const r = await providers.test(id);
      setProbe((p) => ({ ...p, [id]: { ok: r.ok, detail: r.detail } }));
    } catch (e) {
      setProbe((p) => ({ ...p, [id]: { ok: false, detail: String(e) } }));
    } finally {
      setProbing(null);
    }
  }

  async function saveKey(id: string) {
    try {
      await providers.setKey(id, keyDraft[id] ?? "");
      setKeyDraft((d) => ({ ...d, [id]: "" }));
      await refresh();
    } catch (e) {
      setErr(String(e));
    }
  }

  // Key-optional providers only (Vertex AI): drop a stored token override and
  // return to the hands-off auth path (ADC). Without this, a stale pasted token
  // would shadow ADC forever.
  async function clearKey(id: string) {
    try {
      await providers.deleteKey(id);
      await refresh();
    } catch (e) {
      setErr(String(e));
    }
  }

  return (
    <>
      {err && <div className="settings-err">{err}</div>}
      <p className="settings-hint">
        Bring your own key — pick any OpenAI-compatible provider. Keys are stored in the OS
        keychain and never read back. Click a model to use it now; add any model name your
        provider accepts, remove ones you don't use (×), and the eye chooses which appear in
        the chat's model picker.
      </p>
      {listLoading && list.length === 0 && (
        <div className="settings-loading" role="status" aria-live="polite">
          <span className="spinner" aria-hidden="true" />
          Loading providers…
        </div>
      )}
      <ul className="provider-list">
        {list.map((p) => {
          const cat = catalogFor(p);
          const q = (modelQuery[p.id] ?? "").trim().toLowerCase();
          const matches = q ? cat.filter((m) => m.toLowerCase().includes(q)) : cat;
          const isCapped = !q && !expanded[p.id] && matches.length > MODEL_CHIP_CAP;
          const chips = isCapped ? matches.slice(0, MODEL_CHIP_CAP) : matches;
          return (
          <li key={p.id} className={p.id === active.provider ? "active" : ""}>
            <div className="provider-row">
              <span className="provider-label">
                {p.label} {p.is_local && <em>(local)</em>}
              </span>
              <span className="provider-row-right">
                <button
                  className="provider-test"
                  disabled={loading === p.id || (p.requires_key && !p.has_key)}
                  onClick={() => void loadModels(p)}
                  title="Load this provider's available models from its endpoint"
                >
                  {loading === p.id ? "Loading…" : "Load models"}
                </button>
                <button
                  className="provider-test"
                  disabled={probing === p.id || (p.requires_key && !p.has_key)}
                  onClick={() => void testProvider(p.id)}
                  title="Test the connection"
                >
                  {probing === p.id ? "Testing…" : "Test"}
                </button>
                <span className={`key-badge ${p.has_key ? "ok" : "missing"}`}>
                  {p.requires_key
                    ? p.has_key
                      ? "key set"
                      : "no key"
                    : p.key_optional
                      ? p.has_key
                        ? "token set"
                        : "cloud auth"
                      : "no key needed"}
                </span>
              </span>
            </div>
            {probe[p.id] && (
              <div className={`provider-probe ${probe[p.id].ok ? "ok" : "err"}`}>
                {probe[p.id].ok ? "✓ " : "✕ "}
                {probe[p.id].detail}
              </div>
            )}
            {(p.requires_key || p.key_optional) && (
              <div className="key-entry">
                <input
                  type="password"
                  placeholder={p.key_optional ? `${p.label} access token (optional)` : `${p.label} API key`}
                  aria-label={p.key_optional ? `${p.label} access token (optional)` : `${p.label} API key`}
                  value={keyDraft[p.id] ?? ""}
                  onChange={(e) => setKeyDraft((d) => ({ ...d, [p.id]: e.target.value }))}
                />
                <button onClick={() => saveKey(p.id)} disabled={!(keyDraft[p.id] ?? "").trim()}>
                  Save
                </button>
                {p.key_optional && p.has_key && (
                  <button
                    onClick={() => void clearKey(p.id)}
                    title="Remove the stored token and go back to Google Cloud ADC"
                  >
                    Clear
                  </button>
                )}
              </div>
            )}
            {p.key_hint && <p className="key-hint">{p.key_hint}</p>}
            {cat.length >= MODEL_SEARCH_MIN && (
              <div className="model-tools">
                <span className="model-search">
                  <Icon name="search" size={12} />
                  <input
                    value={modelQuery[p.id] ?? ""}
                    onChange={(e) => setModelQuery((d) => ({ ...d, [p.id]: e.target.value }))}
                    placeholder={`Search ${cat.length} models…`}
                    aria-label={`Search ${p.label} models`}
                    spellCheck={false}
                    autoCapitalize="off"
                    autoCorrect="off"
                  />
                  {q && (
                    <button
                      className="model-search-clear"
                      aria-label={`Clear ${p.label} model search`}
                      title="Clear"
                      onClick={() => setModelQuery((d) => ({ ...d, [p.id]: "" }))}
                    >
                      <Icon name="x" size={11} />
                    </button>
                  )}
                </span>
                <span className="model-count" aria-live="polite">
                  {q ? `${matches.length} of ${cat.length} match` : `${cat.length} models`}
                </span>
              </div>
            )}
            <div className="model-row">
              {chips.map((m) => {
                const isActive = p.id === active.provider && m === active.model;
                const isShown = shown(p, m);
                const isCustom = (custom[p.id] ?? []).includes(m);
                return (
                  <span
                    key={m}
                    className={`model-chip ${isActive ? "active" : ""} ${isShown ? "" : "off"} ${isCustom ? "custom" : ""}`}
                  >
                    <button
                      className="model-pick"
                      onClick={() => onPick(p.id, m)}
                      disabled={p.requires_key && !p.has_key}
                    >
                      {m}
                    </button>
                    <button
                      className="model-vis"
                      role="switch"
                      aria-checked={isShown}
                      aria-label={`Show ${m} in the chat model picker`}
                      title={isShown ? "Shown in the chat model picker — click to hide" : "Hidden from the chat model picker — click to show"}
                      onClick={() => toggleShown(p, m)}
                    >
                      <Icon name="eye" size={12} />
                    </button>
                    <button
                      className="model-del"
                      aria-label={`Remove ${m} from ${p.label}`}
                      title="Remove this model"
                      onClick={() => removeModel(p, m)}
                    >
                      <Icon name="x" size={11} />
                    </button>
                  </span>
                );
              })}
              {q && matches.length === 0 && (
                <span className="model-none">No models match “{(modelQuery[p.id] ?? "").trim()}”.</span>
              )}
              {isCapped && (
                <button
                  className="model-more"
                  onClick={() => setExpanded((d) => ({ ...d, [p.id]: true }))}
                >
                  Show all {matches.length} models
                </button>
              )}
              {!q && expanded[p.id] && matches.length > MODEL_CHIP_CAP && (
                <button
                  className="model-more"
                  onClick={() => setExpanded((d) => ({ ...d, [p.id]: false }))}
                >
                  Show fewer
                </button>
              )}
              <form
                className="model-add"
                onSubmit={(e) => {
                  e.preventDefault();
                  addModel(p, modelDraft[p.id] ?? "");
                }}
              >
                <input
                  value={modelDraft[p.id] ?? ""}
                  onChange={(e) => setModelDraft((d) => ({ ...d, [p.id]: e.target.value }))}
                  placeholder="Add model…"
                  aria-label={`Add a custom model to ${p.label}`}
                  spellCheck={false}
                  autoCapitalize="off"
                  autoCorrect="off"
                />
                <button
                  type="submit"
                  className="model-add-btn"
                  disabled={!(modelDraft[p.id] ?? "").trim()}
                  aria-label={`Add model to ${p.label}`}
                  title="Add this model"
                >
                  <Icon name="plus" size={12} />
                </button>
              </form>
            </div>
          </li>
          );
        })}
      </ul>
    </>
  );
}
