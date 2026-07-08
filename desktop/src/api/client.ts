// Typed REST + SSE client for the FastAPI backend. The single seam between the UI
// and the backend; no domain logic lives here.

import { fetchEventSource } from "@microsoft/fetch-event-source";

import type { AgentEvent } from "./events";

// In web dev, Vite proxies "/api" -> backend. In the packaged app, VITE_API_BASE
// points at the bundled backend.
const BASE = (import.meta.env?.VITE_API_BASE as string | undefined) ?? "/api";

let token: string | null = null;
export function setToken(t: string | null): void {
  token = t;
}

function authHeaders(extra?: Record<string, string>): Record<string, string> {
  const h: Record<string, string> = { ...(extra ?? {}) };
  if (token) h["Authorization"] = `Bearer ${token}`;
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

async function request<T>(method: string, path: string, body?: unknown): Promise<T> {
  const resp = await fetch(BASE + path, {
    method,
    headers: authHeaders(body !== undefined ? { "Content-Type": "application/json" } : undefined),
    body: body !== undefined ? JSON.stringify(body) : undefined,
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
}

export const api = {
  get: <T>(p: string) => request<T>("GET", p),
  post: <T>(p: string, body?: unknown) => request<T>("POST", p, body),
  put: <T>(p: string, body?: unknown) => request<T>("PUT", p, body),
  patch: <T>(p: string, body?: unknown) => request<T>("PATCH", p, body),
  del: <T>(p: string) => request<T>("DELETE", p),
};

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
}

export const settings = {
  get: () => api.get<AppSettings>("/settings"),
  save: (patch: Partial<AppSettings>) => api.put<AppSettings>("/settings", patch),
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
}

// The backend routes non-project chats under this implicit project.
export const GENERAL_PROJECT = "general";

export interface Project {
  id: string;
  name: string;
  created_at?: string;
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
  list: () => api.get<Project[]>("/projects"),
  create: (name: string) => api.post<Project>("/projects", { name }),
  del: (pid: string) => api.del<{ ok: boolean }>(`/projects/${pid}`),
  getInstructions: (pid: string) => api.get<{ content: string }>(`/projects/${pid}/instructions`),
  saveInstructions: (pid: string, content: string) =>
    api.put<{ ok: boolean }>(`/projects/${pid}/instructions`, { content }),
  capacity: (pid: string) => api.get<Capacity>(`/projects/${pid}/capacity`),
  files: (pid: string) => api.get<ProjectFile[]>(`/projects/${pid}/files`),
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
  save: (pid: string, cid: string, messages: StoredMsg[], title?: string) =>
    api.put<ConversationDetail>(`/projects/${pid}/conversations/${cid}`, { messages, title }),
  rename: (pid: string, cid: string, title: string) =>
    api.patch<{ ok: boolean }>(`/projects/${pid}/conversations/${cid}`, { title }),
  generateTitle: (firstMessage: string) =>
    api.post<{ title: string }>("/conversations/title", { first_message: firstMessage }),
  setPinned: (pid: string, cid: string, pinned: boolean) =>
    api.patch<{ ok: boolean }>(`/projects/${pid}/conversations/${cid}`, { pinned }),
  move: (pid: string, cid: string, dstProjectId: string) =>
    api.post<{ ok: boolean }>(`/projects/${pid}/conversations/${cid}/move`, { dst_project_id: dstProjectId }),
  del: (pid: string, cid: string) => api.del<{ ok: boolean }>(`/projects/${pid}/conversations/${cid}`),
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
  status: string;
  detail: string;
  tool_count: number;
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

export interface CoworkTask {
  id: string;
  title: string;
  status: "running" | "done" | "error" | "cancelled";
  created_at: string;
  updated_at: string;
  events: number;
}

export interface CoworkDetail extends CoworkTask {
  goal: string;
  error: string | null;
  event_list: import("./events").AgentEvent[];
  answer: string;
}

export const cowork = {
  list: () => api.get<CoworkTask[]>("/cowork"),
  start: (body: { goal: string; model: string; provider?: string | null; effort?: string; project_id?: string | null }) =>
    api.post<CoworkTask>("/cowork", body),
  get: (id: string) => api.get<CoworkDetail>(`/cowork/${id}`),
  cancel: (id: string) => api.post<{ cancelled: boolean }>(`/cowork/${id}/cancel`),
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
}

export const skills = {
  list: () => api.get<SkillSummary[]>("/skills"),
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
  filename: string;
  installed: boolean;
}

export const plugins = {
  list: () => api.get<PluginSummary[]>("/plugins"),
  marketplace: () => api.get<MarketplacePlugin[]>("/marketplace"),
  install: (name: string) => api.post<{ ok: boolean; name: string }>("/marketplace/install", { name }),
  uninstall: (name: string) =>
    api.post<{ ok: boolean; name: string }>("/marketplace/uninstall", { name }),
};

export const mcp = {
  list: () => api.get<McpServer[]>("/mcp-servers"),
  add: (body: AddMcpBody) => api.post<McpServer>("/mcp-servers", body),
  addDemo: () => api.post<McpServer>("/mcp-servers/demo"),
  remove: (sid: string) => api.del<{ ok: boolean }>(`/mcp-servers/${sid}`),
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
};

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
