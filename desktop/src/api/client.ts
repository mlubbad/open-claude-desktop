// Typed REST + SSE client for the FastAPI backend. The single seam between the UI
// and the backend; no domain logic lives here.

import { fetchEventSource } from "@microsoft/fetch-event-source";

import type { AgentEvent } from "./events";

// API base resolution, in precedence order:
//   1. VITE_API_BASE — an explicit build-time override.
//   2. Running inside the Tauri shell → the bundled backend on loopback. (A packaged
//      static build has no Vite dev-proxy, so "/api" is unreachable there — this is
//      what makes the shipped app able to reach its own sidecar.)
//   3. Web dev → "/api", which the Vite dev server proxies to the backend.
function tauriApiBase(): string | null {
  if (typeof window === "undefined") return null;
  const w = window as unknown as { __TAURI__?: unknown; __TAURI_INTERNALS__?: unknown };
  return w.__TAURI__ || "__TAURI_INTERNALS__" in w ? "http://127.0.0.1:8000" : null;
}
const BASE = (import.meta.env?.VITE_API_BASE as string | undefined) ?? tauriApiBase() ?? "/api";

// Whether we're running inside the Tauri desktop shell (which owns the backend sidecar's
// lifecycle). The backend-health banner only applies here — on the web the backend runs
// separately and isn't ours to watch/restart.
export function isTauriShell(): boolean {
  return tauriApiBase() !== null;
}

// The per-launch local API token the shell injects into the webview (window
// .__OCD_API_TOKEN__). Sent as X-OCD-Token so the loopback backend can tell the app
// apart from a web page probing the port. Absent in dev → no header, no enforcement.
function localApiToken(): string | null {
  if (typeof window === "undefined") return null;
  const t = (window as unknown as { __OCD_API_TOKEN__?: unknown }).__OCD_API_TOKEN__;
  return typeof t === "string" && t ? t : null;
}

let token: string | null = null;
export function setToken(t: string | null): void {
  token = t;
}

function authHeaders(extra?: Record<string, string>): Record<string, string> {
  const h: Record<string, string> = { ...(extra ?? {}) };
  if (token) h["Authorization"] = `Bearer ${token}`;
  const lt = localApiToken();
  if (lt) h["X-OCD-Token"] = lt;
  return h;
}

export class ApiError extends Error {
  constructor(
    public status: number,
    public detail: string,
  ) {
    super(`${status}: ${detail}`);
  }
}

// A hung request (backend deadlocked, connection stalled) would otherwise leave the UI
// spinner spinning forever. Bound every JSON REST call with a generous deadline — the
// SSE agent turn (streamTurn) and multipart uploads are separate paths, so nothing slow-
// but-legitimate rides through here; the ceiling only trips on a genuine hang.
const REQUEST_TIMEOUT_MS = 120_000;

async function request<T>(method: string, path: string, body?: unknown,
                          timeoutMs = REQUEST_TIMEOUT_MS): Promise<T> {
  const ctrl = new AbortController();
  const timer = setTimeout(() => ctrl.abort(), timeoutMs);
  try {
    const resp = await fetch(BASE + path, {
      method,
      headers: authHeaders(body !== undefined ? { "Content-Type": "application/json" } : undefined),
      body: body !== undefined ? JSON.stringify(body) : undefined,
      signal: ctrl.signal,
    });
    if (!resp.ok) {
      let detail = resp.statusText;
      try {
        detail = (await resp.json())?.detail ?? detail;
      } catch {
        /* keep statusText */
      }
      throw new ApiError(resp.status, detail);
    }
    return (await resp.json()) as T;
  } catch (e) {
    // Turn an abort (our own deadline) into a clear, typed error instead of a bare
    // DOMException the callers don't know how to render.
    if (ctrl.signal.aborted) throw new ApiError(408, `request timed out after ${timeoutMs}ms`);
    throw e;
  } finally {
    clearTimeout(timer);
  }
}

export const api = {
  get: <T>(p: string) => request<T>("GET", p),
  post: <T>(p: string, body?: unknown) => request<T>("POST", p, body),
  put: <T>(p: string, body?: unknown) => request<T>("PUT", p, body),
  patch: <T>(p: string, body?: unknown) => request<T>("PATCH", p, body),
  del: <T>(p: string) => request<T>("DELETE", p),
};

// Liveness probe for the backend sidecar. Hits /healthz (exempt from the token gate),
// with a short timeout, and returns a boolean instead of throwing so a polling caller
// stays trivial. Used by the "backend unreachable" banner while the shell auto-restarts.
export async function checkBackendHealth(timeoutMs = 4000): Promise<boolean> {
  const ctrl = new AbortController();
  const t = setTimeout(() => ctrl.abort(), timeoutMs);
  try {
    const resp = await fetch(BASE + "/healthz", { signal: ctrl.signal });
    return resp.ok;
  } catch {
    return false;
  } finally {
    clearTimeout(t);
  }
}

export interface ProviderInfo {
  id: string;
  label: string;
  is_local: boolean;
  requires_key: boolean;
  has_key: boolean;
  default_model: string;
  models: string[];
  docs: string;
  is_default: boolean;
}

export interface UserProfile {
  name?: string;
  call_me?: string;
  role?: string;
  about?: string;
  preferences?: string;
}

export interface AppSettings {
  model?: string;
  provider?: string;
  effort?: string;
  theme?: string;
  profile?: UserProfile;
  search_provider?: string; // "ddg" (keyless default) | "searxng"
  searxng_url?: string;
  code_execution?: string; // "auto" | "docker" | "local" | "off"
  permission_mode?: string; // "strict" | "ask" | "auto" (HITL autonomy)
  memory_search?: boolean; // agent may search past chats mid-turn
  autonomy_paused?: boolean; // global kill-switch for unattended (Cowork/scheduled) runs
  // Which models each provider shows in the chat model picker; empty/missing
  // provider entry = the picker's default (the first few of the catalog).
  visible_models?: Record<string, string[]>;
  // Opik observability (opt-in): mirror agent turns into traces on a self-hosted
  // or Cloud Opik instance. The API key is NOT here — it lives in the OS keychain
  // (set via observability.setKey); these are non-secret config only.
  opik_enabled?: boolean;
  opik_mode?: string; // "local" | "cloud"
  opik_url?: string;
  opik_project?: string;
  opik_workspace?: string;
}

// Settings are read on mount by several components (the three Settings pages, the model
// picker, and App). They only ever change through save() here, so cache the fetched
// settings and refresh the cache on save — collapsing N independent get()s into one
// request and removing the per-page content flash on the Settings modal / model picker.
let _settingsCache: Promise<AppSettings> | null = null;

export const settings = {
  get: (): Promise<AppSettings> => {
    if (!_settingsCache) {
      _settingsCache = api.get<AppSettings>("/settings").catch((e) => {
        _settingsCache = null; // never cache a failure — let the next call retry
        throw e;
      });
    }
    return _settingsCache;
  },
  save: async (patch: Partial<AppSettings>): Promise<AppSettings> => {
    const updated = await api.put<AppSettings>("/settings", patch);
    _settingsCache = Promise.resolve(updated); // keep the cache authoritative post-save
    return updated;
  },
  // Force the next get() to hit the network. save() already refreshes the cache, so this
  // is rarely needed — it's here for a deliberate "reload settings" affordance.
  invalidate: () => {
    _settingsCache = null;
  },
};

// A redacted operational snapshot for "Export diagnostics" / bug reports (no secrets;
// the personal profile is reduced to a presence flag by the backend).
export const diagnostics = {
  get: (): Promise<Record<string, unknown>> =>
    api.get<Record<string, unknown>>("/diagnostics"),
};

// Opik observability status (the API key itself is never returned — only has_key).
export interface ObservabilityStatus {
  enabled: boolean;
  mode: string; // "local" | "cloud"
  url: string;
  project: string;
  workspace: string;
  has_key: boolean;
  sdk_installed: boolean;
}

export const observability = {
  get: () => api.get<ObservabilityStatus>("/observability"),
  setKey: (key: string) => api.put<{ has_key: boolean }>("/observability/key", { key }),
  clearKey: () => api.del<{ has_key: boolean }>("/observability/key"),
};

export const providers = {
  list: () => api.get<ProviderInfo[]>("/providers"),
  setKey: (id: string, key: string) => api.put<{ id: string; has_key: boolean }>(`/providers/${id}/key`, { key }),
  deleteKey: (id: string) => api.del<{ id: string; has_key: boolean }>(`/providers/${id}/key`),
  test: (id: string) => api.post<{ id: string; ok: boolean; detail: string }>(`/providers/${id}/test`),
};

export interface AgentTurnRequest {
  project_id?: string | null;
  goal: string;
  history: { role: string; content: string; kind?: string }[];
  model: string;
  provider?: string | null;
  effort?: string;
  permission_mode?: string | null;
  options?: Record<string, boolean>;
  enabled_plugins?: string[];
  enabled_connectors?: string[];
  enabled_mcp?: string[];
  // data-URI images attached to this message (vision input; bounded server-side).
  images?: string[];
  // Response style: normal | concise | explanatory | formal (or custom text).
  style?: string;
}

// The backend routes non-project chats under this implicit project.
export const GENERAL_PROJECT = "general";

export interface Project {
  id: string;
  name: string;
  description?: string;
  pinned?: boolean;
  archived?: boolean;
  created_at?: string;
  updated_at?: string;
  updated_rel?: string;
}

export interface ProjectPatch {
  name?: string;
  description?: string;
  pinned?: boolean;
  archived?: boolean;
}

export interface Capacity {
  used_mb: number;
  max_mb: number;
  percent: number;
}

export interface ProjectFile {
  name: string;
  badge: string;
  size: number;
  meta?: string;
}

export const projects = {
  list: (archived = false) => api.get<Project[]>(`/projects${archived ? "?archived=true" : ""}`),
  create: (name: string, description = "") => api.post<Project>("/projects", { name, description }),
  update: (pid: string, patch: ProjectPatch) => api.patch<Project>(`/projects/${pid}`, patch),
  del: (pid: string) => api.del<{ ok: boolean }>(`/projects/${pid}`),
  getInstructions: (pid: string) => api.get<{ content: string }>(`/projects/${pid}/instructions`),
  saveInstructions: (pid: string, content: string) =>
    api.put<{ ok: boolean }>(`/projects/${pid}/instructions`, { content }),
  getMemory: (pid: string) => api.get<{ content: string; updated_rel: string }>(`/projects/${pid}/memory`),
  capacity: (pid: string) => api.get<Capacity>(`/projects/${pid}/capacity`),
  files: (pid: string) => api.get<ProjectFile[]>(`/projects/${pid}/files`),
  removeFile: (pid: string, name: string) =>
    api.del<{ ok: boolean }>(`/projects/${pid}/files/${encodeURIComponent(name)}`),
  reindexFile: (pid: string, name: string) =>
    api.post<{ ok: boolean; chunks: number }>(
      `/projects/${pid}/files/${encodeURIComponent(name)}/reindex`, {}),
  uploadFile: async (pid: string, file: File) => {
    const form = new FormData();
    form.append("file", file);
    const resp = await fetch(`${BASE}/projects/${pid}/files`, {
      method: "POST",
      headers: authHeaders(), // no Content-Type: the browser sets the multipart boundary
      body: form,
    });
    if (!resp.ok) throw new ApiError(resp.status, await resp.text());
    return (await resp.json()) as { ok: boolean; name: string; chunks: number };
  },
};

export interface ConversationSummary {
  id: string;
  title: string;
  updated_at: string;
  updated_rel?: string;
  pinned: boolean;
  project_id?: string;
  project_name?: string;
}

export interface StoredMsg {
  role: string;
  content: string;
  kind: string;
}

export interface ConversationDetail extends ConversationSummary {
  messages: StoredMsg[];
  parent_id?: string | null; // set when this conversation is a branch of another
  fork_index?: number | null; // the message index it was forked at
  version?: number; // optimistic-concurrency version, bumped on every save
}

// One node in a branch family (the tree of conversations linked by parent_id).
export interface BranchNode {
  id: string;
  title: string;
  parent_id: string | null;
  fork_index: number | null;
  updated_at: string;
  project_id: string;
}
export interface BranchFamily {
  root: string | null;
  current: string;
  nodes: BranchNode[];
}

// A search hit: a conversation summary plus where it matched and a context snippet.
export interface ConversationSearchHit extends ConversationSummary {
  matched_in: string;
  snippet: string;
}

export const conversations = {
  listAll: (limit = 200) => api.get<ConversationSummary[]>(`/conversations?limit=${limit}`),
  search: (q: string, limit = 50) =>
    api.get<ConversationSearchHit[]>(`/conversations/search?q=${encodeURIComponent(q)}&limit=${limit}`),
  create: (pid: string, firstMessage: string) =>
    api.post<ConversationDetail>(`/projects/${pid}/conversations`, { first_message: firstMessage }),
  get: (pid: string, cid: string) => api.get<ConversationDetail>(`/projects/${pid}/conversations/${cid}`),
  save: (pid: string, cid: string, messages: StoredMsg[], title?: string, version?: number) =>
    api.put<ConversationDetail>(`/projects/${pid}/conversations/${cid}`, { messages, title, version }),
  rename: (pid: string, cid: string, title: string) =>
    api.patch<{ ok: boolean }>(`/projects/${pid}/conversations/${cid}`, { title }),
  generateTitle: (firstMessage: string) =>
    api.post<{ title: string }>("/conversations/title", { first_message: firstMessage }),
  setPinned: (pid: string, cid: string, pinned: boolean) =>
    api.patch<{ ok: boolean }>(`/projects/${pid}/conversations/${cid}`, { pinned }),
  move: (pid: string, cid: string, dstProjectId: string) =>
    api.post<{ ok: boolean }>(`/projects/${pid}/conversations/${cid}/move`, { dst_project_id: dstProjectId }),
  del: (pid: string, cid: string) => api.del<{ ok: boolean }>(`/projects/${pid}/conversations/${cid}`),
  // Fork the conversation at a message → a new branch conversation (a copy of the
  // history up to that point, linked to the parent).
  branch: (pid: string, cid: string, atIndex: number) =>
    api.post<ConversationDetail>(`/projects/${pid}/conversations/${cid}/branch`, { at_index: atIndex }),
  // The branch family (tree) a conversation belongs to, for the switcher.
  branches: (pid: string, cid: string) =>
    api.get<BranchFamily>(`/projects/${pid}/conversations/${cid}/branches`),
};

export interface McpServer {
  id: string;
  name: string;
  transport: string;
  command: string;
  args: string[];
  url: string;
  auth: boolean;
  auth_mode?: string; // "oauth" for OAuth 2.1 connectors, else ""
  authorized?: boolean; // OAuth connectors: whether a token is held
  source: string; // "mcpb" for one-click-installed extensions, else ""
  version: string;
  repository: string; // manifest repository URL — enables the update check (P1-13)
  status: string;
  detail: string;
  tool_count: number;
  tools: string[]; // tool names (for the per-tool toggles)
  disabled_tools: string[]; // tools the user switched off (P1-12)
}

export interface AddMcpBody {
  name: string;
  command?: string;
  args?: string[];
  url?: string;
  transport?: string;
  env?: Record<string, string>;
  headers?: Record<string, string>;
  auth_token?: string;
}

// Result of an extension update check (P1-13). `latest` is null when current.
export interface McpUpdateInfo {
  current: string;
  latest: string | null;
  url: string;
  notes: string;
}

// A field the user must fill in before an extension can launch (API keys, paths…).
export interface UserConfigField {
  type?: string;
  title?: string;
  description?: string;
  required?: boolean;
  sensitive?: boolean;
  default?: string;
}

export interface McpbManifestInfo {
  name: string;
  version: string;
  description: string;
  author: unknown;
  user_config: Record<string, UserConfigField>;
}

// Multipart POST for file uploads (no JSON Content-Type — the browser sets the
// multipart boundary). Shares auth + error handling with request().
async function postForm<T>(path: string, form: FormData): Promise<T> {
  const resp = await fetch(BASE + path, { method: "POST", headers: authHeaders(), body: form });
  if (!resp.ok) {
    let detail = resp.statusText;
    try {
      detail = (await resp.json())?.detail ?? detail;
    } catch {
      /* keep statusText */
    }
    throw new ApiError(resp.status, detail);
  }
  return (await resp.json()) as T;
}

export type CoworkStatus = "running" | "done" | "error" | "cancelled" | "interrupted";

export interface CoworkTask {
  id: string;
  title: string;
  status: CoworkStatus;
  approval: "skip" | "manual";
  project_id?: string | null;
  created_at: string;
  updated_at: string;
  events: number;
}

export interface CoworkFile {
  name: string;
  kind: string;
}
export interface CoworkProgress {
  label: string;
  done: boolean;
}

export interface CoworkDetail extends CoworkTask {
  goal: string;
  error: string | null;
  turn_id: string | null;
  event_list: import("./events").AgentEvent[];
  answer: string;
  files: CoworkFile[];
  progress: CoworkProgress[];
}

export const cowork = {
  list: () => api.get<CoworkTask[]>("/cowork"),
  start: (body: {
    goal: string; model: string; provider?: string | null; effort?: string;
    project_id?: string | null; approval?: "skip" | "manual";
  }) => api.post<CoworkTask>("/cowork", body),
  get: (id: string) => api.get<CoworkDetail>(`/cowork/${id}`),
  cancel: (id: string) => api.post<{ cancelled: boolean }>(`/cowork/${id}/cancel`),
  clear: () => api.post<{ cleared: number }>("/cowork/clear", {}),
};

export interface Schedule {
  id: string;
  goal: string;
  kind: "interval" | "daily";
  every_seconds?: number | null;
  at?: string | null;
  enabled: boolean;
  last_run?: string | null;
  title: string;
  cadence: string;
}

export interface AddScheduleBody {
  goal: string;
  kind: "interval" | "daily";
  every_seconds?: number | null;
  at?: string | null;
  model?: string;
  provider?: string | null;
  effort?: string;
  project_id?: string | null;
}

export const schedules = {
  list: () => api.get<Schedule[]>("/schedules"),
  add: (body: AddScheduleBody) => api.post<Schedule>("/schedules", body),
  remove: (id: string) => api.del<{ ok: boolean }>(`/schedules/${id}`),
  setEnabled: (id: string, enabled: boolean) =>
    api.post<Schedule>(`/schedules/${id}/enabled`, { enabled }),
};

export interface CodeEntry {
  path: string;
  type: "file" | "dir";
  size: number;
}

export interface CodeFile {
  path?: string;
  content?: string;
  binary?: boolean;
  size?: number;
  truncated?: boolean;
  error?: string;
}

export const code = {
  tree: (project?: string) =>
    api.get<{ project: string; entries: CodeEntry[] }>(
      `/code/tree${project ? `?project=${encodeURIComponent(project)}` : ""}`,
    ),
  file: (path: string, project?: string) =>
    api.get<CodeFile>(
      `/code/file?path=${encodeURIComponent(path)}${project ? `&project=${encodeURIComponent(project)}` : ""}`,
    ),
};

// Download a workspace file a code_execution run produced (a chart PNG, the merged CSV…).
// Fetches with auth (a plain <a href> wouldn't carry the token), then saves it as a blob.
export async function downloadWorkspaceFile(path: string, project?: string): Promise<void> {
  const url =
    `${BASE}/code/download?path=${encodeURIComponent(path)}` +
    (project ? `&project=${encodeURIComponent(project)}` : "");
  const resp = await fetch(url, { headers: authHeaders() });
  if (!resp.ok) throw new ApiError(resp.status, resp.statusText);
  const blob = await resp.blob();
  const objUrl = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = objUrl;
  a.download = path.split("/").pop() || "file";
  a.click();
  URL.revokeObjectURL(objUrl);
}

export interface SkillSummary {
  name: string;
  description?: string;
  auto?: boolean;
  triggers?: string[];
  imported?: boolean; // user-imported (removable) vs bundled
}

export const skills = {
  list: () => api.get<SkillSummary[]>("/skills"),
  import: (filename: string, content: string) =>
    api.post<{ ok: boolean; name: string }>("/skills", { filename, content }),
  // A .zip of a skill folder (SKILL.md + references/) — extracted server-side.
  importZip: (file: File) => {
    const form = new FormData();
    form.append("file", file);
    return postForm<{ ok: boolean; count: number; names: string[] }>("/skills/import-zip", form);
  },
  importFromRepo: (url: string, ref = "") =>
    api.post<{ ok: boolean; count: number; names: string[] }>("/skills/from-repo", { url, ref }),
  remove: (name: string) => api.del<{ ok: boolean }>(`/skills/${encodeURIComponent(name)}`),
};

export interface PluginSummary {
  name: string;
  description?: string;
  tool?: unknown;
}

export interface MarketplacePlugin {
  name: string;
  description: string;
  category: string;
  filename?: string;
  installed: boolean;
  origin?: string; // "bundled" or the synced source's name
  source_id?: string | null;
}

// A synced repository source (a git repo cloned locally that contributes plugins).
export interface MarketplaceSource {
  id: string;
  name: string;
  url: string;
  ref: string;
  added_at: string;
  plugins: number;
  present: boolean;
}

export const plugins = {
  list: () => api.get<PluginSummary[]>("/plugins"),
  marketplace: () => api.get<MarketplacePlugin[]>("/marketplace"),
  install: (name: string) => api.post<{ ok: boolean; name: string }>("/marketplace/install", { name }),
  uninstall: (name: string) =>
    api.post<{ ok: boolean; name: string }>("/marketplace/uninstall", { name }),
  // Repository marketplace sources (sync plugins from a git URL).
  sources: () => api.get<{ allow_remote: boolean; sources: MarketplaceSource[] }>("/marketplace/sources"),
  addSource: (url: string, ref = "", name = "") =>
    api.post<{ ok: boolean; source: MarketplaceSource }>("/marketplace/sources", { url, ref, name }),
  removeSource: (id: string) => api.del<{ ok: boolean }>(`/marketplace/sources/${id}`),
};

export const mcp = {
  list: () => api.get<McpServer[]>("/mcp-servers"),
  add: (body: AddMcpBody) => api.post<McpServer>("/mcp-servers", body),
  remove: (sid: string) => api.del<{ ok: boolean }>(`/mcp-servers/${sid}`),
  // Re-connect from scratch (the error card's Retry) — recovers a first-run
  // download timeout or a fixed PATH without removing and re-adding.
  refresh: (sid: string) => api.post<McpServer>(`/mcp-servers/${sid}/refresh`, {}),
  // One-click desktop-extension bundles (.mcpb / legacy .dxt).
  inspect: (file: File) => {
    const form = new FormData();
    form.append("file", file);
    return postForm<McpbManifestInfo>("/mcp-servers/inspect", form);
  },
  install: (file: File, userConfig: Record<string, string> = {}) => {
    const form = new FormData();
    form.append("file", file);
    form.append("user_config", JSON.stringify(userConfig));
    return postForm<McpServer>("/mcp-servers/install", form);
  },
  // OAuth 2.1 remote connectors: register, then authorize (opens the browser).
  addOAuth: (name: string, url: string, transport = "http") =>
    api.post<McpServer>("/mcp-servers/oauth", { name, url, transport }),
  authorize: (sid: string) => api.post<McpServer>(`/mcp-servers/${sid}/authorize`),
  // MCP prompts (P1-2): listed per server, rendered on demand for `/` commands.
  prompts: (sid: string) => api.get<{ prompts: McpPromptInfo[] }>(`/mcp-servers/${sid}/prompts`),
  getPrompt: (sid: string, name: string, args: Record<string, string> = {}) =>
    api.post<{ messages: { role: string; content: string }[] }>(
      `/mcp-servers/${sid}/prompts/${encodeURIComponent(name)}`, args),
  // Per-tool enable/disable within a connector (P1-12).
  setToolEnabled: (sid: string, tool: string, enabled: boolean) =>
    api.post<McpServer>(`/mcp-servers/${sid}/tools/${encodeURIComponent(tool)}`, { enabled }),
  // Extension updates (P1-13): check the manifest's GitHub repo for a newer
  // release bundle, then reinstall in place (user_config comes from the keychain).
  checkUpdate: (sid: string) => api.get<McpUpdateInfo>(`/mcp-servers/${sid}/update`),
  update: (sid: string, values: Record<string, string> = {}) =>
    api.post<McpServer>(`/mcp-servers/${sid}/update`, { values }),
  // Curated open-source connector catalog (P1-3); entries prefill the add form.
  directory: () => api.get<DirectoryEntry[]>("/connectors/directory"),
};

export interface McpPromptInfo {
  name: string;
  description?: string;
}

// A curated connector-directory entry ("browse connectors").
export interface DirectoryEntry {
  id: string;
  name: string;
  description: string;
  transport: string; // "stdio" | "http" | "sse"
  command?: string;
  args?: string[];
  url?: string;
  env_keys: string[];
  runtime?: string; // "node" | "python"
  tags: string[];
}

// Stream an agent turn. Invokes onEvent for each typed event; resolves on `done`.
// The returned AbortController lets the caller stop the turn.
export function streamTurn(
  req: AgentTurnRequest,
  onEvent: (ev: AgentEvent) => void,
  onError?: (err: unknown) => void,
): AbortController {
  const ctrl = new AbortController();
  fetchEventSource(BASE + "/agent/turn", {
    method: "POST",
    headers: authHeaders({ "Content-Type": "application/json" }),
    body: JSON.stringify(req),
    signal: ctrl.signal,
    openWhenHidden: true,
    onmessage(msg) {
      if (!msg.data) return;
      let ev: AgentEvent;
      try {
        ev = JSON.parse(msg.data) as AgentEvent;
      } catch {
        return;
      }
      onEvent(ev);
      if (ev.type === "done") ctrl.abort();
    },
    onerror(err) {
      onError?.(err);
      throw err; // stop the built-in retry loop
    },
  }).catch((err) => {
    if (!ctrl.signal.aborted) onError?.(err);
  });
  return ctrl;
}

// Resolve a HITL approval prompt for a running turn.
export function replyPermission(
  turnId: string,
  toolCallId: string,
  decision: "approve" | "decline",
): Promise<{ resolved: boolean; decision: string }> {
  return api.post(`/agent/turn/${turnId}/permission`, { tool_call_id: toolCallId, decision });
}
